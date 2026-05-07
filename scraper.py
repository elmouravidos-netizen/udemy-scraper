"""
Udemy + Multi-Platform Free Courses Scraper  v4
- 10 Udemy sources + Coursera + edX + Alison + FutureLearn + Google Digital Garage
- Keyword & category blocklist — no sport/music/cooking trash
- Dedup by platform:slug key — zero duplicates across all platforms
- Saves to Supabase + udemy_deals.json backup
- Target: 600-1000+ courses per run
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import time
import os
from datetime import datetime, timedelta
from urllib.parse import quote, urljoin

# ── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ── Blocklists ────────────────────────────────────────────────────────────────
BLOCKED_TITLE_KEYWORDS = [
    "yoga", "guitar", "piano", "ukulele", "violin", "drums",
    "cooking", "recipe", "baking", "chef", "food",
    "fitness", "bodybuilding", "workout", "weightlifting",
    "reiki", "astrology", "tarot", "crystal", "chakra", "manifestation",
    "watercolor", "oil painting", "acrylic", "sketching", "knitting",
    "sport", "football", "soccer", "basketball", "cricket",
    "golf", "tennis", "swimming", "surfing", "horse",
    "dog training", "cat ", "pet care", "bird",
    "singing", "vocal", "music theory", "music production",
    "fl studio", "ableton", "dj ", "mixing ",
    "dance", "ballet", "zumba",
    "gardening", "farming", "beekeeping",
    "astrology", "numerology", "psychic",
]

BLOCKED_CATEGORIES = {"music", "health", "photography", "sport"}

# ── Headers ───────────────────────────────────────────────────────────────────
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

UDEMY_HEADERS = {
    **HEADERS,
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}


class MultiPlatformScraper:

    def __init__(self):
        self.courses = {}       # key = "platform:slug" — global dedup
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.stats = {
            "sources":    {},
            "platforms":  {},
            "blocked":    0,
            "expired":    0,
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

    def is_blocked(self, title):
        """Return True if the course title contains blocked keywords."""
        t = title.lower()
        for kw in BLOCKED_TITLE_KEYWORDS:
            if kw in t:
                self.stats["blocked"] += 1
                return True
        return False

    def extract_udemy_slug(self, url):
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
                             "golang","rust","angular","vue","typescript",
                             "flutter","spring","laravel","wordpress"],
            "business":     ["business","marketing","seo","entrepreneur",
                             "management","finance","accounting","sales",
                             "startup","leadership","mba","project management",
                             "agile","scrum","dropshipping","e-commerce",
                             "copywriting","branding","growth hacking"],
            "design":       ["design","photoshop","illustrator","ui ","ux ",
                             "graphic","figma","canva","adobe","blender",
                             "3d","animation","video editing","premiere",
                             "after effects","davinci","logo","web design"],
            "data":         ["data science","machine learning"," ml ","ai ",
                             "analytics","power bi","tableau","deep learning",
                             "nlp","artificial intelligence","pandas","numpy",
                             "tensorflow","pytorch","big data","statistics",
                             "data analysis","r programming","scikit"],
            "it":           ["aws","cloud","linux","networking","cybersecurity",
                             "hacking","comptia","cisco","devops","docker",
                             "kubernetes","azure","gcp","server","terraform",
                             "certified","ethical hacking","pen testing",
                             "it support","system admin","windows server"],
            "personal":     ["personal development","communication",
                             "productivity","time management","mindset",
                             "public speaking","confidence","habits",
                             "self-improvement","critical thinking",
                             "speed reading","memory","study skills"],
            "language":     ["english","spanish","french","arabic","german",
                             "chinese","japanese","language learning",
                             "ielts","toefl","grammar","writing skills"],
        }
        for cat, keywords in cats.items():
            if any(kw in text for kw in keywords):
                return cat
        return "general"

    def clean_title(self, title):
        title = re.sub(r'\s+', ' ', title).strip()
        title = re.sub(
            r'\s*[\|\-–]\s*(udemy|free|course|coupon|coursera|edx|alison).*$',
            '', title, flags=re.I
        )
        return title

    def make_key(self, platform, slug):
        return f"{platform.lower()}:{slug}"

    # ─────────────────────────────────────────────
    # REGISTER COURSE (universal — all platforms)
    # ─────────────────────────────────────────────

    def add_course(self, title, url, source, platform="Udemy",
                   thumbnail=None, description=None, post_html=None):
        if not title or len(title) < 8:
            return False
        title = self.clean_title(title)

        # ── Blocklist check ───────────────────────
        if self.is_blocked(title):
            return False

        # ── Build slug/key ────────────────────────
        if platform == "Udemy":
            slug = self.extract_udemy_slug(url)
        else:
            # For other platforms use URL path as slug
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

        # Blog thumbnail fallback
        blog_thumb = thumbnail
        if not blog_thumb and post_html:
            soup = BeautifulSoup(post_html, "lxml")
            for img in soup.find_all("img"):
                src = img.get("data-src") or img.get("src", "")
                if any(x in src for x in ["udemycdn","udemyassets","480x270","240x135"]):
                    if src.startswith("http"):
                        blog_thumb = src
                        break

        coupon = self.extract_coupon(url) if platform == "Udemy" else None

        self.courses[key] = {
            "id":           key,
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
            "is_expired":   False,
            "scraped_at":   datetime.utcnow().isoformat(),
            "expires_at":   (datetime.utcnow() + timedelta(days=3)).isoformat(),
        }
        self.stats["platforms"][platform] = self.stats["platforms"].get(platform, 0) + 1
        return True

    # ─────────────────────────────────────────────
    # UDEMY THUMBNAIL ENRICHMENT
    # ─────────────────────────────────────────────

    def get_udemy_meta(self, slug):
        url = f"https://www.udemy.com/course/{slug}/"
        try:
            resp = self.session.get(url, timeout=20, headers=UDEMY_HEADERS, allow_redirects=True)
            if resp.status_code != 200:
                return {}
            soup   = BeautifulSoup(resp.text, "lxml")
            result = {}
            og = soup.find("meta", property="og:image")
            if og and og.get("content", "").startswith("http"):
                result["thumbnail"] = og["content"]
            if not result.get("thumbnail"):
                tw = soup.find("meta", attrs={"name": "twitter:image"})
                if tw and tw.get("content", "").startswith("http"):
                    result["thumbnail"] = tw["content"]
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
                    result["title"]       = (data.get("name") or "").strip() or None
                    result["description"] = (data.get("description") or "")[:300] or None
                    author = data.get("author") or data.get("instructor")
                    if isinstance(author, list) and author:
                        author = author[0]
                    if isinstance(author, dict):
                        result["instructor"] = author.get("name")
                    agg = data.get("aggregateRating", {})
                    if agg:
                        result["rating"]   = agg.get("ratingValue")
                        result["students"] = agg.get("ratingCount") or agg.get("reviewCount")
                    break
                except Exception:
                    continue
            return result
        except Exception as e:
            print(f"  ⚠️  Udemy meta: {e}")
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
        print(f"ENRICHING THUMBNAILS — {len(self.courses)} courses")
        print(f"{'='*60}")
        items = list(self.courses.values())
        for i, course in enumerate(items, 1):
            # Only Udemy needs page-scraping for thumbnails
            if course["platform"] == "Udemy" and not course.get("thumbnail"):
                slug = course["id"].split(":", 1)[1]
                print(f"  [{i}/{len(items)}] {course['title'][:50]}...")
                meta = self.get_udemy_meta(slug)
                if meta.get("thumbnail"):
                    course["thumbnail"] = meta["thumbnail"]
                    self.stats["thumbnails"]["real"] += 1
                elif course.get("_blog_thumb"):
                    course["thumbnail"] = course["_blog_thumb"]
                    self.stats["thumbnails"]["blog"] += 1
                else:
                    course["thumbnail"] = self.generate_placeholder(
                        course["title"], course["category"]
                    )
                    self.stats["thumbnails"]["placeholder"] += 1
                for field in ("title","instructor","description"):
                    if meta.get(field) and len(str(meta[field])) > 5:
                        course[field] = meta[field]
                if meta.get("rating"):
                    try: course["rating"] = round(float(meta["rating"]), 1)
                    except: pass
                if meta.get("students"):
                    try: course["students"] = int(meta["students"])
                    except: pass
                if i % batch_size == 0:
                    time.sleep(3)
                else:
                    time.sleep(0.8)
            elif course.get("thumbnail"):
                self.stats["thumbnails"]["real"] += 1
            else:
                course["thumbnail"] = self.generate_placeholder(
                    course["title"], course["category"]
                )
                self.stats["thumbnails"]["placeholder"] += 1
            course.pop("_blog_thumb", None)

        t = self.stats["thumbnails"]
        print(f"\n✅ Real: {t['real']} | Blog: {t['blog']} | Placeholder: {t['placeholder']}")

    # ─────────────────────────────────────────────
    # COUPON VALIDATION (Udemy only)
    # ─────────────────────────────────────────────

    def validate_coupons(self, max_check=50):
        print(f"\n{'='*60}")
        print(f"VALIDATING COUPONS (up to {max_check})")
        print(f"{'='*60}")
        expired_kw = [
            "coupon has expired","no longer available",
            "invalid coupon","promotion expired",
            "coupon code entered is not valid",
        ]
        checked = 0
        for key, course in list(self.courses.items()):
            if course["platform"] != "Udemy":
                continue
            if not course.get("coupon_code") or checked >= max_check:
                continue
            try:
                resp = self.session.get(
                    course["url"], headers=UDEMY_HEADERS, timeout=15, allow_redirects=True
                )
                if any(kw in resp.text.lower() for kw in expired_kw):
                    course["is_expired"] = True
                    self.stats["expired"] += 1
                    print(f"  ❌ {course['title'][:52]}")
                else:
                    print(f"  ✅ {course['title'][:52]}")
                checked += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  {e}")

    # ─────────────────────────────────────────────
    # GENERIC BLOG SCRAPER (Udemy coupon blogs)
    # ─────────────────────────────────────────────

    def scrape_blog(self, name, base_url, max_pages=10):
        print(f"\n[Udemy Source] {name}")
        count = 0
        for page in range(1, max_pages + 1):
            url  = base_url if page == 1 else f"{base_url.rstrip('/')}/page/{page}/"
            html = self.fetch(url)
            if not html:
                break
            soup  = BeautifulSoup(html, "lxml")
            items = (
                soup.find_all("article") or
                soup.find_all("div", class_=re.compile("post|course|card|entry"))
            )
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
            time.sleep(1)
        print(f"  → {count} new courses")
        self.stats["sources"][name] = count
        return count

    # ─────────────────────────────────────────────
    # UDEMY: real.discount (JSON API)
    # ─────────────────────────────────────────────

    def scrape_real_discount(self, max_pages=15):
        print("\n[Udemy Source] real.discount (API)")
        count = 0
        for page in range(1, max_pages + 1):
            try:
                resp = self.session.get(
                    f"https://www.real.discount/api/free-courses/"
                    f"?page={page}&ordering=-date&format=json",
                    timeout=15,
                )
                results = resp.json().get("results", [])
                if not results:
                    break
                print(f"  Page {page}: {len(results)} items")
                for item in results:
                    title     = (item.get("name") or "").strip()
                    udemy_url = item.get("url") or item.get("store_link", "")
                    thumb     = item.get("image") or item.get("thumbnail")
                    if self.add_course(title, udemy_url, "real.discount", "Udemy", thumbnail=thumb):
                        count += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  {e}")
                break
        print(f"  → {count} new courses")
        self.stats["sources"]["real.discount"] = count
        return count

    # ─────────────────────────────────────────────
    # UDEMY: tutorialbar.com
    # ─────────────────────────────────────────────

    def scrape_tutorialbar(self, max_pages=15):
        print("\n[Udemy Source] tutorialbar.com")
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
            time.sleep(1)
        print(f"  → {count} new courses")
        self.stats["sources"]["tutorialbar.com"] = count
        return count

    # ─────────────────────────────────────────────
    # UDEMY: discudemy.com
    # ─────────────────────────────────────────────

    def scrape_discudemy(self, max_pages=15):
        print("\n[Udemy Source] discudemy.com")
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
            time.sleep(1)
        print(f"  → {count} new courses")
        self.stats["sources"]["discudemy.com"] = count
        return count

    # ─────────────────────────────────────────────
    # PLATFORM: Coursera (public API)
    # ─────────────────────────────────────────────

    def scrape_coursera(self, max_pages=10):
        print("\n[Platform] Coursera (free audit courses)")
        count  = 0
        fields = "photoUrl,name,slug,courseStatus,partnerIds,description"
        for page in range(0, max_pages):
            try:
                resp = self.session.get(
                    f"https://api.coursera.org/api/courses.v1"
                    f"?q=search&query=free&fields={fields}"
                    f"&limit=100&start={page * 100}",
                    timeout=15,
                )
                data    = resp.json()
                results = data.get("elements", [])
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
                print(f"  ⚠️  Coursera API: {e}")
                break
        print(f"  → {count} new courses")
        self.stats["sources"]["coursera.org"] = count
        return count

    # ─────────────────────────────────────────────
    # PLATFORM: Alison (always free)
    # ─────────────────────────────────────────────

    def scrape_alison(self, max_pages=10):
        print("\n[Platform] Alison (always free)")
        count      = 0
        categories = [
            "it", "technology", "business", "data-science",
            "language", "personal-development", "marketing",
        ]
        for cat in categories:
            for page in range(1, max_pages + 1):
                url  = f"https://alison.com/courses/{cat}?page={page}"
                html = self.fetch(url)
                if not html:
                    break
                soup  = BeautifulSoup(html, "lxml")
                items = soup.find_all("div", class_=re.compile("course-item|course-card|course_item"))
                if not items:
                    # Try generic article/li
                    items = soup.find_all("li", class_=re.compile("course"))
                if not items:
                    break
                print(f"  [{cat}] Page {page}: {len(items)} items")
                for item in items:
                    title_tag = item.find(["h2", "h3", "h4", "a"])
                    if not title_tag:
                        continue
                    title = title_tag.get_text(strip=True)
                    a     = item.find("a", href=True)
                    if not a:
                        continue
                    href = a["href"]
                    if not href.startswith("http"):
                        href = "https://alison.com" + href
                    thumb_tag = item.find("img")
                    thumb     = None
                    if thumb_tag:
                        thumb = thumb_tag.get("src") or thumb_tag.get("data-src")
                    if self.add_course(title, href, "alison.com", "Alison", thumbnail=thumb):
                        count += 1
                time.sleep(1)
        print(f"  → {count} new courses")
        self.stats["sources"]["alison.com"] = count
        return count

    # ─────────────────────────────────────────────
    # PLATFORM: FutureLearn (free tier)
    # ─────────────────────────────────────────────

    def scrape_futurelearn(self, max_pages=5):
        print("\n[Platform] FutureLearn (free tier)")
        count = 0
        for page in range(1, max_pages + 1):
            url  = f"https://www.futurelearn.com/courses?filter_category=free&page={page}"
            html = self.fetch(url)
            if not html:
                break
            soup  = BeautifulSoup(html, "lxml")
            items = soup.find_all("article") or soup.find_all("li", class_=re.compile("course"))
            if not items:
                break
            print(f"  Page {page}: {len(items)} items")
            for item in items:
                title_tag = item.find(["h2", "h3", "h4"])
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                a     = item.find("a", href=True)
                if not a:
                    continue
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://www.futurelearn.com" + href
                thumb_tag = item.find("img")
                thumb     = None
                if thumb_tag:
                    thumb = (
                        thumb_tag.get("data-src") or
                        thumb_tag.get("src") or
                        thumb_tag.get("data-lazy-src")
                    )
                if self.add_course(title, href, "futurelearn.com", "FutureLearn", thumbnail=thumb):
                    count += 1
            time.sleep(1)
        print(f"  → {count} new courses")
        self.stats["sources"]["futurelearn.com"] = count
        return count

    # ─────────────────────────────────────────────
    # PLATFORM: edX (free audit)
    # ─────────────────────────────────────────────

    def scrape_edx(self, max_pages=5):
        print("\n[Platform] edX (free audit mode)")
        count = 0
        # edX search API (public, no auth needed)
        topics = ["programming","business","data-analysis","computer-science",
                  "language","design","it","finance"]
        for topic in topics:
            try:
                resp = self.session.get(
                    f"https://www.edx.org/api/v1/catalog/search/"
                    f"?q={topic}&availability=Available+now&content_type=course"
                    f"&price=Free&page_size=50",
                    timeout=15,
                )
                results = resp.json().get("objects", {}).get("results", [])
                print(f"  [{topic}]: {len(results)} items")
                for item in results:
                    title = (item.get("title") or "").strip()
                    slug  = item.get("marketing_url", "").rstrip("/").split("/")[-1]
                    url   = item.get("marketing_url") or f"https://www.edx.org/course/{slug}"
                    if not url.startswith("http"):
                        url = "https://www.edx.org" + url
                    thumb = item.get("card_image_url") or item.get("image", {}).get("src")
                    desc  = (item.get("short_description") or "")[:300]
                    if self.add_course(title, url, "edx.org", "edX",
                                       thumbnail=thumb, description=desc):
                        count += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  edX [{topic}]: {e}")
        print(f"  → {count} new courses")
        self.stats["sources"]["edx.org"] = count
        return count

    # ─────────────────────────────────────────────
    # PLATFORM: Google Digital Garage (always free)
    # ─────────────────────────────────────────────

    def scrape_google_digital_garage(self):
        print("\n[Platform] Google Digital Garage")
        count = 0
        try:
            html = self.fetch("https://learndigital.withgoogle.com/digitalgarage/courses")
            if not html:
                return 0
            soup  = BeautifulSoup(html, "lxml")
            items = soup.find_all("li", class_=re.compile("course")) or soup.find_all("article")
            print(f"  Found {len(items)} items")
            for item in items:
                title_tag = item.find(["h2", "h3", "h4", "span"])
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                a     = item.find("a", href=True)
                if not a:
                    continue
                href = a["href"]
                if not href.startswith("http"):
                    href = "https://learndigital.withgoogle.com" + href
                thumb_tag = item.find("img")
                thumb     = thumb_tag.get("src") if thumb_tag else None
                if self.add_course(title, href, "google.com/digitalgarage",
                                   "Google", thumbnail=thumb):
                    count += 1
        except Exception as e:
            print(f"  ⚠️  Google Digital Garage: {e}")
        print(f"  → {count} new courses")
        self.stats["sources"]["google.com/digitalgarage"] = count
        return count

    # ─────────────────────────────────────────────
    # SUPABASE UPSERT
    # ─────────────────────────────────────────────

    def save_to_supabase(self):
        if not self.supabase:
            print("\n⚠️  No Supabase credentials — skipping")
            return
        print(f"\n{'='*60}")
        print("SAVING TO SUPABASE")
        print(f"{'='*60}")
        items      = [
            {k: v for k, v in c.items() if not k.startswith("_")}
            for c in self.courses.values()
        ]
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
        try:
            self.supabase.table("scrape_runs").insert({
                "total_found": len(self.courses),
                "new_courses": saved,
                "expired":     self.stats["expired"],
                "sources":     self.stats["sources"],
            }).execute()
        except Exception:
            pass
        print(f"\n✅ Total saved: {saved}")

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
        print("MULTI-PLATFORM SCRAPER  v4")
        print(f"Platforms: Udemy + Coursera + edX + Alison + FutureLearn + Google")
        print(f"Blocklist: {len(BLOCKED_TITLE_KEYWORDS)} keywords active")
        print(f"{'='*60}")

        # ── Udemy sources ─────────────────────────
        self.scrape_real_discount(max_pages=15)
        self.scrape_tutorialbar(max_pages=15)
        self.scrape_discudemy(max_pages=15)
        self.scrape_blog("couponscorpion.com",   "https://couponscorpion.com",   max_pages=10)
        self.scrape_blog("freebiesglobal.com",   "https://freebiesglobal.com",   max_pages=10)
        self.scrape_blog("coursecouponclub.com", "https://coursecouponclub.com", max_pages=10)
        self.scrape_blog("udemyfree.eu.org",     "https://udemyfree.eu.org",     max_pages=8)
        self.scrape_blog("idownloadcoupon.com",  "https://idownloadcoupon.com",  max_pages=8)
        self.scrape_blog("onlinecourses.ooo",    "https://onlinecourses.ooo",    max_pages=8)
        self.scrape_blog("udemyking.com",        "https://udemyking.com",        max_pages=8)

        # ── Other platforms ───────────────────────
        self.scrape_coursera(max_pages=10)
        self.scrape_edx(max_pages=5)
        self.scrape_alison(max_pages=5)
        self.scrape_futurelearn(max_pages=5)
        self.scrape_google_digital_garage()

        print(f"\n📦 Total unique courses: {len(self.courses)}")
        print(f"🚫 Blocked by filter:   {self.stats['blocked']}")

        self.enrich_thumbnails(batch_size=15)
        self.validate_coupons(max_check=50)
        self.save_to_supabase()
        self.save_json()

        # ── Final report ──────────────────────────
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
        print(f"Blocked/filtered: {self.stats['blocked']}")
        print(f"Expired removed : {self.stats['expired']}")
        print(f"\nBy platform:")
        for p, n in sorted(self.stats["platforms"].items(), key=lambda x: -x[1]):
            print(f"  {p:20} | {n:4} | {'█' * min(n // 5, 30)}")
        print(f"\nBy category:")
        for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
            print(f"  {cat:15} | {n:4} | {'█' * min(n // 3, 30)}")
        print("\n✅ Done!")


if __name__ == "__main__":
    scraper = MultiPlatformScraper()
    scraper.run()
