"""
Multi-Platform Free Courses Scraper  v8
Changes from v7:
  - Rotates User-Agents + retries with backoff on Udemy 403/429
    (fixes description/instructor/rating/language coming back empty)
  - Detects REAL course_language from Udemy page instead of assuming English
  - NEVER hard-deletes courses anymore (was breaking SEO via 404s on
    already-indexed pages) — marks is_expired = True instead
  - Auto-expires courses past their estimated coupon window
  - Every upserted row gets content_status='pending' so the separate
    Arabic content-enrichment workflow knows what to process
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import time
import os
import random
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

BLOCKED_TITLE_KEYWORDS = [
    "yoga", "guitar", "piano", "ukulele", "violin", "drums",
    "cooking", "recipe", "baking", "chef",
    "fitness", "bodybuilding", "workout", "weightlifting",
    "reiki", "astrology", "tarot", "crystal", "chakra",
    "watercolor", "oil painting", "acrylic", "knitting",
    "football", "soccer", "basketball", "cricket",
    "golf", "tennis", "swimming", "surfing",
    "dog training", "pet care",
    "singing", "vocal", "music theory",
    "fl studio", "ableton", "dj mixing",
    "dance", "ballet", "zumba",
    "gardening", "farming", "beekeeping",
    "numerology", "psychic",
]

BLOCKED_CATEGORIES = {"music", "health", "photography", "sport"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Rotate user-agents — Udemy fingerprints and blocks a single static UA
# hit repeatedly from a datacenter IP (GitHub Actions runners).
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 "
    "Firefox/126.0",
]


def get_udemy_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.google.com/",
    }


class MultiPlatformScraper:

    def __init__(self):
        self.courses    = {}
        self.session    = requests.Session()
        self.session.headers.update(HEADERS)
        self.run_id     = datetime.utcnow().isoformat()
        self.stats      = {
            "sources":    {},
            "platforms":  {},
            "blocked":    0,
            "expired":    0,
            "cleaned":    0,
            "thumbnails": {"real": 0, "blog": 0, "placeholder": 0},
        }
        self.supabase = None
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                from supabase import create_client
                self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                print("✅ Supabase connected")
            except Exception as e:
                print(f"⚠️  Supabase error: {e}")

    # ─────────────────────────────────────────────
    # UTILITIES
    # ─────────────────────────────────────────────

    def fetch(self, url, retries=3, delay=1.0, custom_headers=None):
        for attempt in range(retries):
            try:
                resp = self.session.get(
                    url, timeout=20,
                    headers=custom_headers or HEADERS,
                    allow_redirects=True,
                )
                if resp.status_code == 429:
                    wait = 5 * (attempt + 1)
                    print(f"  ⏳ Rate limited — waiting {wait}s")
                    time.sleep(wait)
                    continue
                if resp.status_code in (403, 503):
                    print(f"  🚫 Blocked ({resp.status_code})")
                    return None
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                print(f"  ❌ {e}")
            if attempt < retries - 1:
                time.sleep(delay)
        return None

    def clean_title(self, title):
        """Remove 'Expired' prefix and other junk from titles."""
        title = re.sub(r'^expired\s*', '', title, flags=re.I).strip()
        title = re.sub(r'\s+', ' ', title).strip()
        title = re.sub(
            r'\s*[\|\-–]\s*(udemy|free|course|coupon).*$',
            '', title, flags=re.I
        )
        return title

    def is_expired_title(self, title):
        """Detect if title was prefixed with Expired."""
        return bool(re.match(r'^expired\s+', title, re.I))

    def is_blocked(self, title):
        t = title.lower()
        for kw in BLOCKED_TITLE_KEYWORDS:
            if kw in t:
                self.stats["blocked"] += 1
                return True
        return False

    def extract_slug(self, url):
        if not url:
            return None
        m = re.search(r'udemy\.com/course/([^/?#]+)', url)
        return m.group(1).lower().strip('/') if m else None

    def extract_coupon(self, url):
        if not url:
            return None
        m = re.search(r'[?&]coupon[Cc]ode=([A-Za-z0-9_\-]+)', url)
        return m.group(1) if m else None

    def detect_category(self, title, desc=""):
        text = (title + " " + (desc or "")).lower()
        cats = {
            "programming":  ["python","java","javascript","coding","programming",
                             "developer","html","css","react","node","django",
                             "php","kotlin","android","ios","swift","c++","c#",
                             "golang","rust","angular","vue","typescript","flutter",
                             "spring","laravel","wordpress","git","linux"],
            "business":     ["business","marketing","seo","entrepreneur","management",
                             "finance","accounting","sales","startup","leadership",
                             "mba","project management","agile","scrum","dropshipping",
                             "e-commerce","copywriting","branding"],
            "design":       ["design","photoshop","illustrator","ui ","ux ","graphic",
                             "figma","canva","adobe","blender","3d","animation",
                             "video editing","premiere","after effects","davinci","logo"],
            "data":         ["data science","machine learning"," ml ","ai ","analytics",
                             "power bi","tableau","deep learning","nlp",
                             "artificial intelligence","pandas","numpy","tensorflow",
                             "pytorch","big data","statistics","data analysis"],
            "it":           ["aws","cloud","linux","networking","cybersecurity",
                             "hacking","comptia","cisco","devops","docker",
                             "kubernetes","azure","gcp","server","terraform",
                             "certified","ethical hacking","pen testing","it support"],
            "personal":     ["personal development","communication","productivity",
                             "time management","mindset","public speaking",
                             "confidence","habits","self-improvement"],
            "language":     ["english","spanish","french","arabic","german",
                             "chinese","japanese","language learning","ielts","toefl"],
        }
        for cat, keywords in cats.items():
            if any(kw in text for kw in keywords):
                return cat
        return "general"

    def make_key(self, platform, slug):
        return f"{platform.lower()}:{slug}"

    # ─────────────────────────────────────────────
    # REGISTER COURSE
    # ─────────────────────────────────────────────

    def add_course(self, title, url, source, platform="Udemy",
                   thumbnail=None, description=None, post_html=None):
        if not title or len(title) < 8:
            return False

        expired_from_title = self.is_expired_title(title)
        title = self.clean_title(title)

        if self.is_blocked(title):
            return False

        if platform == "Udemy":
            slug = self.extract_slug(url)
        else:
            slug = re.sub(r'[^a-z0-9\-]', '-',
                          url.rstrip('/').split('/')[-1].lower())[:80]
        if not slug:
            return False

        key = self.make_key(platform, slug)
        if key in self.courses:
            return False

        cat = self.detect_category(title, description or "")
        if cat in BLOCKED_CATEGORIES:
            self.stats["blocked"] += 1
            return False

        blog_thumb = thumbnail
        if not blog_thumb and post_html:
            soup = BeautifulSoup(post_html, "lxml")
            for img in soup.find_all("img"):
                src = img.get("data-src") or img.get("src", "")
                if any(x in src for x in ["udemycdn", "udemyassets", "480x270", "240x135"]):
                    if src.startswith("http"):
                        blog_thumb = src
                        break

        coupon = self.extract_coupon(url) if platform == "Udemy" else None
        now    = datetime.utcnow().isoformat()

        self.courses[key] = {
            "id":           key,
            "slug":         slug,
            "title":        title,
            "url":          url,
            "platform":     platform,
            "coupon_code":  coupon,
            "category":     cat,
            "source":       source,
            "_blog_thumb":  blog_thumb,
            "thumbnail":    thumbnail if platform != "Udemy" else None,
            "instructor":   None,
            "description":  description,
            "rating":       None,
            "students":     None,
            "course_language": None,   # filled in by enrich_thumbnails(), never hardcoded
            "is_expired":   expired_from_title,
            "scraped_at":   now,
            "last_seen_at": now,
            "expires_at":   (datetime.utcnow() + timedelta(days=3)).isoformat(),
            "content_status": "pending",  # Arabic enrichment workflow picks this up
        }
        self.stats["platforms"][platform] = self.stats["platforms"].get(platform, 0) + 1
        return True

    # ─────────────────────────────────────────────
    # THUMBNAIL + METADATA ENRICHMENT
    # ─────────────────────────────────────────────

    def get_udemy_meta(self, slug, retries=3):
        url = f"https://www.udemy.com/course/{slug}/"
        for attempt in range(retries):
            try:
                resp = self.session.get(
                    url, timeout=20, headers=get_udemy_headers(), allow_redirects=True
                )
                if resp.status_code == 403:
                    wait = 4 * (attempt + 1) + random.uniform(1, 3)
                    print(f"  🚫 403 on {slug} — backing off {wait:.1f}s (attempt {attempt+1}/{retries})")
                    time.sleep(wait)
                    continue
                if resp.status_code == 429:
                    wait = 6 * (attempt + 1)
                    print(f"  ⏳ Rate limited on {slug} — waiting {wait}s")
                    time.sleep(wait)
                    continue
                if resp.status_code != 200:
                    return {}

                soup = BeautifulSoup(resp.text, "lxml")
                result = {}

                og = soup.find("meta", property="og:image")
                if og and og.get("content", "").startswith("http"):
                    result["thumbnail"] = og["content"]
                if not result.get("thumbnail"):
                    tw = soup.find("meta", attrs={"name": "twitter:image"})
                    if tw and tw.get("content", "").startswith("http"):
                        result["thumbnail"] = tw["content"]

                # Real course language, straight from the page <html lang="">
                html_tag = soup.find("html")
                if html_tag and html_tag.get("lang"):
                    result["course_language"] = html_tag["lang"].split("-")[0]

                for script in soup.find_all("script", type="application/ld+json"):
                    try:
                        data = json.loads(script.string or "")
                        if isinstance(data, list):
                            data = next((d for d in data if d.get("@type") == "Course"), {})
                        if data.get("@type") != "Course":
                            continue
                        if not result.get("thumbnail"):
                            img = data.get("image")
                            if isinstance(img, str) and img.startswith("http"):
                                result["thumbnail"] = img
                            elif isinstance(img, dict):
                                result["thumbnail"] = img.get("url", "")
                        result["title"] = (data.get("name") or "").strip() or None
                        result["description"] = (data.get("description") or "")[:500] or None
                        if data.get("inLanguage"):
                            result["course_language"] = str(data["inLanguage"]).split("-")[0]
                        author = data.get("author") or data.get("instructor")
                        if isinstance(author, list) and author:
                            author = author[0]
                        if isinstance(author, dict):
                            result["instructor"] = author.get("name")
                        agg = data.get("aggregateRating", {})
                        if agg:
                            result["rating"] = agg.get("ratingValue")
                            result["students"] = agg.get("ratingCount") or agg.get("reviewCount")
                        break
                    except Exception:
                        continue

                result.setdefault("course_language", None)
                return result

            except Exception as e:
                print(f"  ⚠️  Udemy meta attempt {attempt+1} failed for {slug}: {e}")
                time.sleep(2 * (attempt + 1))

        return {}

    def generate_placeholder(self, title, category):
        colors = {
            "programming": "3b82f6", "business": "10b981",
            "design":      "8b5cf6", "data":     "f59e0b",
            "it":          "ef4444", "personal": "ec4899",
            "language":    "f97316", "general":  "6b7280",
        }
        return (
            f"https://via.placeholder.com/480x270/"
            f"{colors.get(category, '6b7280')}/ffffff?text={quote(title[:28])}"
        )

    def enrich_thumbnails(self, batch_size=15):
        print(f"\n{'='*60}")
        print(f"ENRICHING THUMBNAILS + METADATA — {len(self.courses)} courses")
        print(f"{'='*60}")

        udemy_page_needed = [
            c for c in self.courses.values()
            if c["platform"] == "Udemy" and not c.get("thumbnail") and not c.get("_blog_thumb")
        ]
        already_have = len(self.courses) - len(udemy_page_needed)
        print(f"  ✅ Already have thumbnail : {already_have}")
        print(f"  🌐 Need Udemy page visit  : {len(udemy_page_needed)}")

        items   = list(self.courses.values())
        visited = 0

        for i, course in enumerate(items, 1):

            if course.get("thumbnail"):
                self.stats["thumbnails"]["real"] += 1
                course.pop("_blog_thumb", None)
                continue

            if course.get("_blog_thumb"):
                course["thumbnail"] = course.pop("_blog_thumb")
                self.stats["thumbnails"]["blog"] += 1
                continue

            if course["platform"] == "Udemy":
                slug = course["id"].split(":", 1)[1]
                print(f"  [{visited+1}/{len(udemy_page_needed)}] {course['title'][:50]}...")
                meta = self.get_udemy_meta(slug)

                if meta.get("thumbnail"):
                    course["thumbnail"] = meta["thumbnail"]
                    self.stats["thumbnails"]["real"] += 1
                else:
                    course["thumbnail"] = self.generate_placeholder(
                        course["title"], course["category"]
                    )
                    self.stats["thumbnails"]["placeholder"] += 1

                for field in ("title", "instructor", "description", "course_language"):
                    if meta.get(field) and len(str(meta[field])) > 1:
                        course[field] = meta[field]
                if meta.get("rating"):
                    try: course["rating"] = round(float(meta["rating"]), 1)
                    except: pass
                if meta.get("students"):
                    try: course["students"] = int(meta["students"])
                    except: pass

                visited += 1
                if visited % batch_size == 0:
                    print(f"  ⏸️  Batch pause...")
                    time.sleep(3)
                else:
                    time.sleep(0.8)
            else:
                course["thumbnail"] = self.generate_placeholder(
                    course["title"], course["category"]
                )
                self.stats["thumbnails"]["placeholder"] += 1

            course.pop("_blog_thumb", None)

        t = self.stats["thumbnails"]
        print(f"\n✅ Real: {t['real']} | Blog: {t['blog']} | Placeholder: {t['placeholder']}")
        print(f"🌐 Udemy pages visited: {visited}")

    # ─────────────────────────────────────────────
    # COUPON VALIDATION
    # ─────────────────────────────────────────────

    def validate_coupons(self, max_check=50):
        print(f"\n{'='*60}")
        print(f"VALIDATING COUPONS (up to {max_check})")
        print(f"{'='*60}")
        expired_kw = [
            "coupon has expired", "no longer available",
            "invalid coupon", "promotion expired",
            "coupon code entered is not valid",
        ]
        checked = 0
        # Prioritize courses closest to their estimated expiry first
        candidates = [
            c for c in self.courses.values()
            if c["platform"] == "Udemy" and c.get("coupon_code")
        ]
        candidates.sort(key=lambda c: c.get("expires_at") or "")

        for course in candidates:
            if checked >= max_check:
                break
            try:
                resp = self.session.get(
                    course["url"], headers=get_udemy_headers(), timeout=15, allow_redirects=True
                )
                if any(kw in resp.text.lower() for kw in expired_kw):
                    course["is_expired"] = True
                    self.stats["expired"] += 1
                    print(f"  ❌ {course['title'][:52]}")
                else:
                    course["last_verified_at"] = datetime.utcnow().isoformat()
                    print(f"  ✅ {course['title'][:52]}")
                checked += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  {e}")
        print(f"\nExpired: {self.stats['expired']}")

    # ─────────────────────────────────────────────
    # GENERIC BLOG SCRAPER
    # ─────────────────────────────────────────────

    def scrape_blog(self, name, base_url, max_pages=10):
        print(f"\n[Source] {name}")
        count = 0
        for page in range(1, max_pages + 1):
            url  = base_url if page == 1 else f"{base_url.rstrip('/')}/page/{page}/"
            html = self.fetch(url)
            if not html:
                print(f"  ⚠️  {name} failed on page {page} — stopping")
                break
            soup  = BeautifulSoup(html, "lxml")
            items = (
                soup.find_all("article") or
                soup.find_all("div", class_=re.compile("post|course|card|entry"))
            )
            if not items:
                print(f"  ⚠️  No items found on page {page} — stopping")
                break
            print(f"  Page {page}: {len(items)} items")
            for item in items:
                title_tag = item.find(["h2", "h3", "h4"])
                if not title_tag:
                    continue
                a        = title_tag.find("a", href=True)
                title    = title_tag.get_text(strip=True)
                post_url = a["href"] if a else None
                if not post_url:
                    continue
                if not post_url.startswith("http"):
                    post_url = urljoin(base_url, post_url)
                post_html = udemy_url = None
                if "udemy.com/course/" in post_url:
                    udemy_url = post_url
                else:
                    post_html = self.fetch(post_url)
                    if post_html:
                        ps = BeautifulSoup(post_html, "lxml")
                        for link in ps.find_all("a", href=True):
                            if "udemy.com/course/" in link["href"]:
                                udemy_url = link["href"]
                                break
                if self.add_course(title, udemy_url, name, "Udemy", post_html=post_html):
                    count += 1
            time.sleep(1.5)
        print(f"  → {count} new courses from {name}")
        self.stats["sources"][name] = count
        return count

    # ─────────────────────────────────────────────
    # coursevania.com (JSON API)
    # ─────────────────────────────────────────────

    def scrape_coursevania(self, max_pages=15):
        print("\n[Source] coursevania.com (API)")
        count = 0
        api_headers = {
            **HEADERS,
            "Accept":  "application/json, text/plain, */*",
            "Referer": "https://coursevania.com/",
        }
        for page in range(1, max_pages + 1):
            try:
                resp = self.session.get(
                    f"https://coursevania.com/wp-json/wp/v2/posts"
                    f"?per_page=20&page={page}&_embed=1",
                    timeout=20,
                    headers=api_headers,
                )
                if page == 1:
                    print(f"  Status: {resp.status_code}")
                if resp.status_code == 400:
                    break
                if resp.status_code != 200:
                    print(f"  ⚠️  Status {resp.status_code} — stopping")
                    break
                results = resp.json()
                if not results:
                    break
                print(f"  Page {page}: {len(results)} items")
                for item in results:
                    title = item.get("title", {}).get("rendered", "").strip()
                    title = re.sub(r'<[^>]+>', '', title)
                    content   = item.get("content", {}).get("rendered", "")
                    udemy_url = None
                    m = re.search(r'https?://www\.udemy\.com/course/[^"\'>\s]+', content)
                    if m:
                        udemy_url = m.group(0).rstrip('/')
                    thumb = None
                    embedded = item.get("_embedded", {})
                    media    = embedded.get("wp:featuredmedia", [{}])
                    if media and isinstance(media, list):
                        src = media[0].get("source_url")
                        if src and src.startswith("http"):
                            thumb = src
                    if self.add_course(title, udemy_url, "coursevania.com", "Udemy",
                                       thumbnail=thumb):
                        count += 1
                time.sleep(0.8)
            except Exception as e:
                print(f"  ⚠️  coursevania page {page}: {e}")
                break
        print(f"  → {count} new courses from coursevania.com")
        self.stats["sources"]["coursevania.com"] = count
        return count

    # ─────────────────────────────────────────────
    # comidoc.net (JSON API)
    # ─────────────────────────────────────────────

    def scrape_comidoc(self, max_pages=15):
        print("\n[Source] comidoc.net (API)")
        count = 0
        api_headers = {
            **HEADERS,
            "Accept":  "application/json, text/plain, */*",
            "Referer": "https://www.comidoc.net/",
        }
        for page in range(1, max_pages + 1):
            try:
                resp = self.session.get(
                    f"https://www.comidoc.net/api/courses"
                    f"?page={page}&limit=20&price=free&ordering=-date",
                    timeout=20,
                    headers=api_headers,
                )
                if page == 1:
                    print(f"  Status: {resp.status_code}")
                if resp.status_code != 200:
                    print(f"  ⚠️  Status {resp.status_code} — stopping")
                    break
                data    = resp.json()
                results = (
                    data if isinstance(data, list) else
                    data.get("results") or
                    data.get("courses") or
                    data.get("data") or []
                )
                if not results:
                    break
                print(f"  Page {page}: {len(results)} items")
                for item in results:
                    title = (
                        item.get("title") or
                        item.get("name") or ""
                    ).strip()
                    udemy_url = (
                        item.get("url") or
                        item.get("udemy_url") or
                        item.get("link") or ""
                    ).strip()
                    thumb = (
                        item.get("image") or
                        item.get("thumbnail") or
                        item.get("image_480x270") or ""
                    ).strip() or None
                    coupon = (
                        item.get("coupon_code") or
                        item.get("coupon") or
                        self.extract_coupon(udemy_url)
                    )
                    if coupon and udemy_url and "couponCode" not in udemy_url:
                        udemy_url = f"{udemy_url}?couponCode={coupon}"
                    if self.add_course(title, udemy_url, "comidoc.net", "Udemy",
                                       thumbnail=thumb):
                        count += 1
                time.sleep(0.8)
            except Exception as e:
                print(f"  ⚠️  comidoc page {page}: {e}")
                break
        print(f"  → {count} new courses from comidoc.net")
        self.stats["sources"]["comidoc.net"] = count
        return count

    # ─────────────────────────────────────────────
    # udemyfreecourses.org (blog — no Cloudflare)
    # ─────────────────────────────────────────────

    def scrape_udemyfreecourses(self, max_pages=10):
        print("\n[Source] udemyfreecourses.org")
        count = 0
        for page in range(1, max_pages + 1):
            url  = ("https://www.udemyfreecourses.org/" if page == 1
                    else f"https://www.udemyfreecourses.org/page/{page}/")
            html = self.fetch(url)
            if not html:
                break
            soup  = BeautifulSoup(html, "lxml")
            items = soup.find_all("article") or soup.find_all("div", class_=re.compile("post|course"))
            if not items:
                break
            print(f"  Page {page}: {len(items)} items")
            for item in items:
                title_tag = item.find(["h2", "h3", "h4"])
                if not title_tag:
                    continue
                a        = title_tag.find("a", href=True)
                title    = title_tag.get_text(strip=True)
                post_url = a["href"] if a else None
                if not post_url:
                    continue
                if not post_url.startswith("http"):
                    post_url = urljoin("https://www.udemyfreecourses.org", post_url)
                post_html = udemy_url = None
                if "udemy.com/course/" in post_url:
                    udemy_url = post_url
                else:
                    post_html = self.fetch(post_url)
                    if post_html:
                        ps = BeautifulSoup(post_html, "lxml")
                        for link in ps.find_all("a", href=True):
                            if "udemy.com/course/" in link["href"]:
                                udemy_url = link["href"]
                                break
                if self.add_course(title, udemy_url, "udemyfreecourses.org",
                                   "Udemy", post_html=post_html):
                    count += 1
            time.sleep(1.5)
        print(f"  → {count} new courses from udemyfreecourses.org")
        self.stats["sources"]["udemyfreecourses.org"] = count
        return count

    # ─────────────────────────────────────────────
    # free-courses.eu (blog — no Cloudflare)
    # ─────────────────────────────────────────────

    def scrape_free_courses_eu(self, max_pages=10):
        print("\n[Source] free-courses.eu")
        count = 0
        for page in range(1, max_pages + 1):
            url  = ("https://www.free-courses.eu/" if page == 1
                    else f"https://www.free-courses.eu/page/{page}/")
            html = self.fetch(url)
            if not html:
                break
            soup  = BeautifulSoup(html, "lxml")
            items = soup.find_all("article") or soup.find_all("div", class_=re.compile("post|course"))
            if not items:
                break
            print(f"  Page {page}: {len(items)} items")
            for item in items:
                title_tag = item.find(["h2", "h3", "h4"])
                if not title_tag:
                    continue
                a        = title_tag.find("a", href=True)
                title    = title_tag.get_text(strip=True)
                post_url = a["href"] if a else None
                if not post_url:
                    continue
                if not post_url.startswith("http"):
                    post_url = urljoin("https://www.free-courses.eu", post_url)
                post_html = udemy_url = None
                if "udemy.com/course/" in post_url:
                    udemy_url = post_url
                else:
                    post_html = self.fetch(post_url)
                    if post_html:
                        ps = BeautifulSoup(post_html, "lxml")
                        for link in ps.find_all("a", href=True):
                            if "udemy.com/course/" in link["href"]:
                                udemy_url = link["href"]
                                break
                if self.add_course(title, udemy_url, "free-courses.eu",
                                   "Udemy", post_html=post_html):
                    count += 1
            time.sleep(1.5)
        print(f"  → {count} new courses from free-courses.eu")
        self.stats["sources"]["free-courses.eu"] = count
        return count

    # ─────────────────────────────────────────────
    # tutorialbar.com
    # ─────────────────────────────────────────────

    def scrape_tutorialbar(self, max_pages=15):
        print("\n[Source] tutorialbar.com")
        count = 0
        for page in range(1, max_pages + 1):
            html = self.fetch(f"https://www.tutorialbar.com/all-courses/page/{page}/")
            if not html:
                break
            soup  = BeautifulSoup(html, "lxml")
            items = soup.find_all("h3", class_="course_title")
            if not items:
                break
            print(f"  Page {page}: {len(items)} items")
            for item in items:
                a = item.find("a", href=True)
                if not a:
                    continue
                title     = a.get_text(strip=True)
                post_html = self.fetch(a["href"])
                udemy_url = None
                if post_html:
                    ps = BeautifulSoup(post_html, "lxml")
                    for link in ps.find_all("a", href=True):
                        if "udemy.com/course/" in link["href"]:
                            udemy_url = link["href"]
                            break
                if self.add_course(title, udemy_url, "tutorialbar.com", "Udemy", post_html=post_html):
                    count += 1
            time.sleep(1.5)
        print(f"  → {count} new courses from tutorialbar.com")
        self.stats["sources"]["tutorialbar.com"] = count
        return count

    # ─────────────────────────────────────────────
    # discudemy.com
    # ─────────────────────────────────────────────

    def scrape_discudemy(self, max_pages=15):
        print("\n[Source] discudemy.com")
        count = 0
        for page in range(1, max_pages + 1):
            html = self.fetch(f"https://www.discudemy.com/all/{page}")
            if not html:
                break
            soup  = BeautifulSoup(html, "lxml")
            items = soup.find_all("div", class_="card-header")
            if not items:
                break
            print(f"  Page {page}: {len(items)} items")
            for item in items:
                a = item.find("a", href=True)
                if not a:
                    continue
                title = a.get_text(strip=True)
                href  = a["href"]
                if not href.startswith("http"):
                    href = "https://www.discudemy.com" + href
                post_html = self.fetch(href)
                udemy_url = None
                if post_html:
                    ps = BeautifulSoup(post_html, "lxml")
                    for link in ps.find_all("a", href=True):
                        if "udemy.com/course/" in link["href"]:
                            udemy_url = link["href"]
                            break
                if self.add_course(title, udemy_url, "discudemy.com", "Udemy", post_html=post_html):
                    count += 1
            time.sleep(1.5)
        print(f"  → {count} new courses from discudemy.com")
        self.stats["sources"]["discudemy.com"] = count
        return count

    # ─────────────────────────────────────────────
    # Coursera (public API)
    # ─────────────────────────────────────────────

    def scrape_coursera(self, max_pages=5):
        print("\n[Platform] Coursera")
        count  = 0
        fields = "photoUrl,name,slug,description"
        for page in range(0, max_pages):
            try:
                resp = self.session.get(
                    f"https://api.coursera.org/api/courses.v1"
                    f"?q=search&query=free&fields={fields}"
                    f"&limit=100&start={page * 100}",
                    timeout=15,
                )
                results = resp.json().get("elements", [])
                if not results:
                    break
                print(f"  Page {page+1}: {len(results)} items")
                for item in results:
                    title = (item.get("name") or "").strip()
                    slug  = item.get("slug", "")
                    if not slug:
                        continue
                    url   = f"https://www.coursera.org/learn/{slug}"
                    thumb = item.get("photoUrl")
                    if thumb and not thumb.startswith("http"):
                        thumb = "https:" + thumb
                    desc  = (item.get("description") or "")[:300]
                    if self.add_course(title, url, "coursera.org", "Coursera",
                                       thumbnail=thumb, description=desc):
                        count += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  Coursera: {e}")
                break
        print(f"  → {count} new courses from Coursera")
        self.stats["sources"]["coursera.org"] = count
        return count

    # ─────────────────────────────────────────────
    # ✅ SUPABASE — Save + mark stale (NEVER delete)
    # ─────────────────────────────────────────────

    def save_to_supabase(self):
        if not self.supabase:
            print("\n⚠️  No Supabase credentials — skipping")
            return
        print(f"\n{'='*60}")
        print("SAVING TO SUPABASE")
        print(f"{'='*60}")

        items = [
            {k: v for k, v in c.items() if not k.startswith("_")}
            for c in self.courses.values()
        ]
        for item in items:
            item.setdefault("content_status", "pending")

        batch_size = 50
        saved      = 0

        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            try:
                result = (
                    self.supabase.table("udemy_courses")
                    .upsert(batch, on_conflict="id")
                    .execute()
                )
                n      = len(result.data) if result.data else len(batch)
                saved += n
                print(f"  ✅ Batch {i//batch_size + 1}: {n} upserted")
            except Exception as e:
                print(f"  ❌ Batch error: {e}")

        # ✅ FIX: mark stale courses instead of deleting them.
        # Deleting a row that Google already indexed turns it into a 404,
        # which damages SEO. Flag it instead — the page stays live.
        print("\n🏷️  Marking stale courses as expired (no deletes)...")
        try:
            cutoff = (datetime.utcnow() - timedelta(days=8)).isoformat()
            result = (
                self.supabase.table("udemy_courses")
                .update({"is_expired": True})
                .lt("scraped_at", cutoff)
                .eq("is_expired", False)
                .execute()
            )
            marked = len(result.data) if result.data else 0
            self.stats["cleaned"] = marked
            print(f"  🏷️  Marked {marked} stale courses as expired (kept in DB)")
        except Exception as e:
            print(f"  ⚠️  Expiry marking error: {e}")

        # Auto-expire anything past its estimated coupon window
        try:
            now = datetime.utcnow().isoformat()
            result = (
                self.supabase.table("udemy_courses")
                .update({"is_expired": True})
                .lt("expires_at", now)
                .eq("is_expired", False)
                .execute()
            )
            expired_now = len(result.data) if result.data else 0
            print(f"  ⏰ Auto-expired {expired_now} courses past their coupon window")
        except Exception as e:
            print(f"  ⚠️  Auto-expire error: {e}")

        try:
            self.supabase.table("scrape_runs").insert({
                "total_found": len(self.courses),
                "new_courses": saved,
                "expired":     self.stats["expired"],
                "sources":     self.stats["sources"],
            }).execute()
        except Exception:
            pass

        print(f"\n✅ Saved: {saved} | Marked stale: {self.stats.get('cleaned', 0)}")

    # ─────────────────────────────────────────────
    # SAVE JSON BACKUP
    # ─────────────────────────────────────────────

    def save_json(self):
        courses_list = [
            {k: v for k, v in c.items() if not k.startswith("_")}
            for c in self.courses.values()
            if not c.get("is_expired")
        ]
        by_cat = {}
        for c in courses_list:
            by_cat.setdefault(c["category"], 0)
            by_cat[c["category"]] += 1
        output = {
            "meta": {
                "scraped_at":    datetime.utcnow().isoformat(),
                "total_courses": len(courses_list),
                "blocked":       self.stats["blocked"],
                "expired":       self.stats["expired"],
                "cleaned":       self.stats["cleaned"],
                "by_platform":   self.stats["platforms"],
                "source_counts": self.stats["sources"],
            },
            "courses":     courses_list,
            "by_category": by_cat,
        }
        with open("udemy_deals.json", "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Saved udemy_deals.json — {len(courses_list)} courses")

    # ─────────────────────────────────────────────
    # MAIN
    # ─────────────────────────────────────────────

    def run(self):
        start = datetime.utcnow()
        print(f"{'='*60}")
        print("MULTI-PLATFORM SCRAPER  v8")
        print(f"Started: {start.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"Sources: freebiesglobal + coursevania + comidoc + new blogs")
        print(f"{'='*60}")

        # Volume trimmed on purpose: keep daily new-course count within
        # what the Arabic enrichment step (Gemini free tier) can clear
        # same-day. Raise these again once billing is enabled on Gemini.
        self.scrape_coursevania(max_pages=3)
        self.scrape_comidoc(max_pages=3)

        self.scrape_blog("freebiesglobal.com",     "https://freebiesglobal.com",     max_pages=2)
        self.scrape_udemyfreecourses(max_pages=2)
        self.scrape_free_courses_eu(max_pages=2)
        self.scrape_blog("udemyfree.eu.org",       "https://udemyfree.eu.org",       max_pages=2)
        self.scrape_blog("idownloadcoupon.com",    "https://idownloadcoupon.com",    max_pages=2)
        self.scrape_tutorialbar(max_pages=2)
        self.scrape_discudemy(max_pages=2)

        self.scrape_coursera(max_pages=1)

        print(f"\n📦 Total unique courses : {len(self.courses)}")
        print(f"🚫 Blocked by filter    : {self.stats['blocked']}")

        self.enrich_thumbnails(batch_size=15)
        self.validate_coupons(max_check=50)
        self.save_to_supabase()
        self.save_json()

        duration = (datetime.utcnow() - start).seconds
        by_cat   = {}
        for c in self.courses.values():
            by_cat.setdefault(c["category"], 0)
            by_cat[c["category"]] += 1

        print(f"\n{'='*60}")
        print("FINAL REPORT")
        print(f"{'='*60}")
        print(f"Duration        : {duration // 60}m {duration % 60}s")
        print(f"Total courses   : {len(self.courses)}")
        print(f"Blocked         : {self.stats['blocked']}")
        print(f"Expired removed : {self.stats['expired']}")
        print(f"Old marked      : {self.stats['cleaned']}")
        print(f"\nBy source:")
        for src, n in sorted(self.stats["sources"].items(), key=lambda x: -x[1]):
            status = "✅" if n > 0 else "❌"
            print(f"  {status} {src:32} | {n:4}")
        print(f"\nBy category:")
        for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
            print(f"  {cat:15} | {n:4} | {'█' * min(n // 10, 30)}")
        print("\n✅ Done!")


if __name__ == "__main__":
    scraper = MultiPlatformScraper()
    scraper.run()
