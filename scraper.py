"""
Udemy Free Courses Scraper  v3
- 10 sources
- Dedup by Udemy course slug (ID) — zero duplicates
- Real thumbnails via Udemy page scraping (og:image / JSON-LD)
- Saves to Supabase (upsert) + udemy_deals.json (backup)
- Target: 500+ courses per run
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import time
import os
from datetime import datetime, timedelta
from urllib.parse import quote

# ── Supabase credentials from env ─────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")   # service_role key

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
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Upgrade-Insecure-Requests": "1",
}


class ProUdemyScraper:

    def __init__(self):
        self.courses = {}          # keyed by course slug — zero duplicates
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.stats = {
            "sources":    {},
            "expired":    0,
            "thumbnails": {"udemy_page": 0, "blog": 0, "placeholder": 0},
        }
        self.supabase = None
        if SUPABASE_URL and SUPABASE_KEY:
            try:
                from supabase import create_client
                self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                print("✅ Supabase connected")
            except Exception as e:
                print(f"⚠️  Supabase connection failed: {e}")

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
            except requests.exceptions.Timeout:
                print(f"  ⏱️  Timeout (attempt {attempt+1})")
            except Exception as e:
                print(f"  ❌ {e}")
            if attempt < retries - 1:
                time.sleep(delay)
        return None

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
            "programming":  ["python","java","javascript","coding","programming","developer",
                             "html","css","react","node","django","php","kotlin","android",
                             "ios","swift","c++","c#","golang","rust","angular","vue",
                             "typescript","flutter","spring","laravel"],
            "business":     ["business","marketing","seo","entrepreneur","management",
                             "finance","accounting","sales","startup","leadership","mba",
                             "project management","agile","scrum","dropshipping","e-commerce"],
            "design":       ["design","photoshop","illustrator","ui ","ux ","graphic",
                             "drawing","figma","canva","adobe","blender","3d","animation",
                             "video editing","premiere","after effects","davinci","logo"],
            "data":         ["data science","machine learning"," ml ","ai ","analytics",
                             "power bi","tableau","deep learning","nlp","artificial intelligence",
                             "pandas","numpy","tensorflow","pytorch","big data"],
            "it":           ["aws","cloud","linux","networking","cybersecurity","hacking",
                             "comptia","cisco","devops","docker","kubernetes","azure","gcp",
                             "server","terraform","certified","ethical hacking"],
            "personal":     ["personal development","communication","productivity",
                             "time management","mindset","meditation","public speaking",
                             "confidence","habits","self-improvement"],
            "photography":  ["photography","camera","lightroom","photo editing","portrait",
                             "landscape","drone"],
            "music":        ["music","guitar","piano","drums","singing","dj","mixing",
                             "music production","fl studio","ableton"],
            "health":       ["health","fitness","yoga","nutrition","diet","mental health",
                             "workout","exercise"],
            "language":     ["english","spanish","french","arabic","german","language",
                             "ielts","toefl"],
        }
        for cat, keywords in cats.items():
            if any(kw in text for kw in keywords):
                return cat
        return "general"

    def clean_title(self, title):
        title = re.sub(r'\s+', ' ', title).strip()
        title = re.sub(r'\s*[\|\-–]\s*(udemy|free|course|coupon).*$', '', title, flags=re.I)
        return title

    # ─────────────────────────────────────────────
    # THUMBNAIL FROM UDEMY COURSE PAGE
    # ─────────────────────────────────────────────

    def get_udemy_meta(self, slug):
        url = f"https://www.udemy.com/course/{slug}/"
        try:
            resp = self.session.get(url, timeout=20, headers=UDEMY_HEADERS, allow_redirects=True)
            if resp.status_code != 200:
                return {}
            soup   = BeautifulSoup(resp.text, "lxml")
            result = {}

            # 1. og:image
            og = soup.find("meta", property="og:image")
            if og and og.get("content", "").startswith("http"):
                result["thumbnail"] = og["content"]

            # 2. twitter:image
            if not result.get("thumbnail"):
                tw = soup.find("meta", attrs={"name": "twitter:image"})
                if tw and tw.get("content", "").startswith("http"):
                    result["thumbnail"] = tw["content"]

            # 3. JSON-LD
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

            # 4. __NEXT_DATA__
            if not result.get("thumbnail"):
                nd = soup.find("script", id="__NEXT_DATA__")
                if nd:
                    try:
                        cd    = json.loads(nd.string or "")
                        cd    = cd.get("props", {}).get("pageProps", {}).get("course", {})
                        thumb = cd.get("image_480x270") or cd.get("image_240x135")
                        if thumb and thumb.startswith("http"):
                            result["thumbnail"] = thumb
                        if not result.get("instructor"):
                            ins = cd.get("visible_instructors", [])
                            if ins:
                                result["instructor"] = ins[0].get("display_name")
                        result.setdefault("rating",   cd.get("rating"))
                        result.setdefault("students", cd.get("num_subscribers"))
                    except Exception:
                        pass
            return result
        except Exception as e:
            print(f"  ⚠️  Udemy meta: {e}")
            return {}

    def generate_placeholder(self, title, category):
        colors = {
            "programming": "3b82f6", "business": "10b981",
            "design":      "8b5cf6", "data":     "f59e0b",
            "it":          "ef4444", "personal": "ec4899",
            "photography": "0ea5e9", "music":    "a855f7",
            "health":      "22c55e", "language": "f97316",
            "general":     "6b7280",
        }
        color = colors.get(category, "6b7280")
        return f"https://via.placeholder.com/480x270/{color}/ffffff?text={quote(title[:28])}"

    # ─────────────────────────────────────────────
    # COURSE REGISTRATION (dedup by slug)
    # ─────────────────────────────────────────────

    def add_course(self, title, udemy_url, source, post_html=None):
        if not title or len(title) < 8:
            return False
        title = self.clean_title(title)
        slug  = self.extract_slug(udemy_url)
        if not slug:
            return False
        if slug in self.courses:
            return False  # Already have it — zero duplicates
        coupon     = self.extract_coupon(udemy_url)
        blog_thumb = None
        if post_html:
            soup = BeautifulSoup(post_html, "lxml")
            for img in soup.find_all("img"):
                src = img.get("data-src") or img.get("src", "")
                if any(x in src for x in ["udemycdn","udemyassets","480x270","240x135"]):
                    if src.startswith("http"):
                        blog_thumb = src
                        break
        self.courses[slug] = {
            "id":           slug,
            "title":        title,
            "url":          udemy_url,
            "coupon_code":  coupon,
            "category":     self.detect_category(title),
            "source":       source,
            "_blog_thumb":  blog_thumb,
            "thumbnail":    None,
            "instructor":   None,
            "description":  None,
            "rating":       None,
            "students":     None,
            "is_expired":   False,
            "scraped_at":   datetime.utcnow().isoformat(),
            "expires_at":   (datetime.utcnow() + timedelta(days=3)).isoformat(),
        }
        return True

    # ─────────────────────────────────────────────
    # THUMBNAIL ENRICHMENT
    # ─────────────────────────────────────────────

    def enrich_thumbnails(self, batch_size=15):
        print(f"\n{'='*60}")
        print(f"ENRICHING THUMBNAILS — {len(self.courses)} courses")
        print(f"{'='*60}")
        items = list(self.courses.values())
        for i, course in enumerate(items, 1):
            slug = course["id"]
            print(f"  [{i}/{len(items)}] {course['title'][:52]}...")
            meta = self.get_udemy_meta(slug)
            if meta.get("thumbnail"):
                course["thumbnail"] = meta["thumbnail"]
                self.stats["thumbnails"]["udemy_page"] += 1
            elif course.get("_blog_thumb"):
                course["thumbnail"] = course["_blog_thumb"]
                self.stats["thumbnails"]["blog"] += 1
            else:
                course["thumbnail"] = self.generate_placeholder(course["title"], course["category"])
                self.stats["thumbnails"]["placeholder"] += 1
            if meta.get("title") and len(meta["title"]) > 10:
                course["title"] = meta["title"]
            for field in ("instructor", "description"):
                if meta.get(field):
                    course[field] = meta[field]
            if meta.get("rating"):
                try:
                    course["rating"] = round(float(meta["rating"]), 1)
                except Exception:
                    pass
            if meta.get("students"):
                try:
                    course["students"] = int(meta["students"])
                except Exception:
                    pass
            course.pop("_blog_thumb", None)
            if i % batch_size == 0:
                print(f"  ⏸️  Batch pause...")
                time.sleep(3)
            else:
                time.sleep(0.8)
        t = self.stats["thumbnails"]
        print(f"\n✅ Udemy: {t['udemy_page']} | Blog: {t['blog']} | Placeholder: {t['placeholder']}")

    # ─────────────────────────────────────────────
    # COUPON VALIDATION
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
        for slug, course in list(self.courses.items()):
            if not course.get("coupon_code") or checked >= max_check:
                continue
            try:
                resp = self.session.get(course["url"], headers=UDEMY_HEADERS, timeout=15, allow_redirects=True)
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
        print(f"\nExpired: {self.stats['expired']}")

    # ─────────────────────────────────────────────
    # GENERIC BLOG SCRAPER (reused by most sources)
    # ─────────────────────────────────────────────

    def scrape_blog(self, name, base_url, max_pages=10, list_selector=None):
        print(f"\n[Source] {name}")
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
                    from urllib.parse import urljoin
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
                if self.add_course(title, udemy_url, name, post_html):
                    count += 1
            time.sleep(1)
        print(f"  → {count} new courses")
        self.stats["sources"][name] = count
        return count

    # ─────────────────────────────────────────────
    # SOURCE: real.discount (has JSON API)
    # ─────────────────────────────────────────────

    def scrape_real_discount(self, max_pages=15):
        print("\n[Source] real.discount (API)")
        count = 0
        for page in range(1, max_pages + 1):
            try:
                resp = self.session.get(
                    f"https://www.real.discount/api/free-courses/?page={page}&ordering=-date&format=json",
                    timeout=15,
                )
                data    = resp.json()
                results = data.get("results", [])
                if not results:
                    break
                print(f"  Page {page}: {len(results)} items")
                for item in results:
                    title     = (item.get("name") or "").strip()
                    udemy_url = item.get("url") or item.get("store_link", "")
                    thumb     = item.get("image") or item.get("thumbnail")
                    if self.add_course(title, udemy_url, "real.discount"):
                        slug = self.extract_slug(udemy_url)
                        if slug and thumb:
                            self.courses[slug]["_blog_thumb"] = thumb
                        count += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️  {e}")
                break
        print(f"  → {count} new courses")
        self.stats["sources"]["real.discount"] = count
        return count

    # ─────────────────────────────────────────────
    # SOURCE: tutorialbar.com
    # ─────────────────────────────────────────────

    def scrape_tutorialbar(self, max_pages=15):
        print("\n[Source] tutorialbar.com")
        count = 0
        for page in range(1, max_pages + 1):
            url  = f"https://www.tutorialbar.com/all-courses/page/{page}/"
            html = self.fetch(url)
            if not html:
                break
            soup  = BeautifulSoup(html, "lxml")
            items = soup.find_all("h3", class_="course_title")
            if not items:
                break
            print(f"  Page {page}: {len(items)} items")
            for item in items:
                a        = item.find("a", href=True)
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
                if self.add_course(title, udemy_url, "tutorialbar.com", post_html):
                    count += 1
            time.sleep(1)
        print(f"  → {count} new courses")
        self.stats["sources"]["tutorialbar.com"] = count
        return count

    # ─────────────────────────────────────────────
    # SOURCE: discudemy.com
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
                title    = a.get_text(strip=True)
                href     = a["href"]
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
                if self.add_course(title, udemy_url, "discudemy.com", post_html):
                    count += 1
            time.sleep(1)
        print(f"  → {count} new courses")
        self.stats["sources"]["discudemy.com"] = count
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
        print(f"\n✅ Total saved to Supabase: {saved}")

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
                "scraped_at":        datetime.utcnow().isoformat(),
                "total_courses":     len(courses_list),
                "expired_removed":   self.stats["expired"],
                "thumbnail_sources": self.stats["thumbnails"],
                "source_counts":     self.stats["sources"],
            },
            "courses":     courses_list,
            "by_category": by_cat,
        }
        with open("udemy_deals.json", "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Saved udemy_deals.json — {len(courses_list)} courses")

    # ─────────────────────────────────────────────
    # MAIN RUN
    # ─────────────────────────────────────────────

    def run(self):
        start = datetime.utcnow()
        print(f"{'='*60}")
        print("UDEMY SCRAPER  v3  —  Professional Edition")
        print(f"10 sources | Supabase upsert | Slug-based dedup")
        print(f"{'='*60}")

        # ── All sources ───────────────────────────
        self.scrape_real_discount(max_pages=15)
        self.scrape_tutorialbar(max_pages=15)
        self.scrape_discudemy(max_pages=15)
        self.scrape_blog("couponscorpion.com",    "https://couponscorpion.com",          max_pages=10)
        self.scrape_blog("freebiesglobal.com",    "https://freebiesglobal.com",          max_pages=10)
        self.scrape_blog("coursecouponclub.com",  "https://coursecouponclub.com",        max_pages=10)
        self.scrape_blog("udemyfree.eu.org",      "https://udemyfree.eu.org",            max_pages=8)
        self.scrape_blog("idownloadcoupon.com",   "https://idownloadcoupon.com",         max_pages=8)
        self.scrape_blog("onlinecourses.ooo",     "https://onlinecourses.ooo",           max_pages=8)
        self.scrape_blog("udemyking.com",         "https://udemyking.com",               max_pages=8)

        print(f"\n📦 Unique courses collected: {len(self.courses)}")

        self.enrich_thumbnails(batch_size=15)
        self.validate_coupons(max_check=50)
        self.save_to_supabase()
        self.save_json()

        # ── Report ────────────────────────────────
        duration = (datetime.utcnow() - start).seconds
        by_cat   = {}
        for c in self.courses.values():
            by_cat.setdefault(c["category"], 0)
            by_cat[c["category"]] += 1

        print(f"\n{'='*60}")
        print("FINAL REPORT")
        print(f"{'='*60}")
        print(f"Duration      : {duration // 60}m {duration % 60}s")
        print(f"Total courses : {len(self.courses)}")
        print(f"Expired       : {self.stats['expired']}")
        print(f"\nBy category:")
        for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
            print(f"  {cat:15} | {n:4} | {'█' * min(n, 30)}")
        print(f"\nBy source:")
        for src, n in sorted(self.stats["sources"].items(), key=lambda x: -x[1]):
            print(f"  {src:32} | {n:4}")
        print("\n✅ Done!")


if __name__ == "__main__":
    scraper = ProUdemyScraper()
    scraper.run()
