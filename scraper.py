import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import re
import time
import urllib.parse

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}

# Separate headers for Udemy requests (mimics a real browser better)
UDEMY_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Upgrade-Insecure-Requests': '1',
}


class UltimateUdemyScraper:

    def __init__(self):
        self.courses = []
        self.seen_titles = set()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.udemy_delay = 1.5  # Seconds between Udemy page requests

    # ─────────────────────────────────────────────
    # CORE FETCH
    # ─────────────────────────────────────────────

    def fetch(self, url, retries=2, custom_headers=None):
        for attempt in range(retries):
            try:
                print(f"  Fetching: {url[:70]}...")
                headers = custom_headers or HEADERS
                resp = self.session.get(url, timeout=20, headers=headers)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                print(f"  Error: {e}")
                if attempt < retries - 1:
                    time.sleep(1.5)
        return None

    # ─────────────────────────────────────────────
    # ✅ FIXED: THUMBNAIL FROM UDEMY COURSE PAGE
    # ─────────────────────────────────────────────

    def get_udemy_course_meta(self, udemy_url):
        """
        Fetch real thumbnail, title, instructor, rating by scraping
        the Udemy course page directly.

        Strategy order:
          1. og:image  meta tag  → most reliable thumbnail
          2. twitter:image meta tag  → good backup
          3. JSON-LD application/ld+json → instructor, rating, students, description
          4. __NEXT_DATA__ JSON embedded in page → fallback for all fields
        """
        if not udemy_url or 'udemy.com/course/' not in udemy_url:
            return None

        # Normalise URL — strip query params for a clean page load,
        # then we'll re-attach the coupon later on the course object.
        clean_url = re.sub(r'\?.*$', '', udemy_url.rstrip('/')) + '/'

        try:
            print(f"  📷 Fetching Udemy page for thumbnail: {clean_url[:60]}...")
            resp = self.session.get(
                clean_url,
                timeout=20,
                headers=UDEMY_HEADERS,
                allow_redirects=True,
            )

            if resp.status_code in (403, 429, 503):
                print(f"  ⚠️  Udemy blocked ({resp.status_code}), skipping")
                return None

            if resp.status_code != 200:
                print(f"  ⚠️  Status {resp.status_code}")
                return None

            soup = BeautifulSoup(resp.text, 'lxml')
            result = {}

            # ── 1. og:image ──────────────────────────────────────────────
            og_img = soup.find('meta', property='og:image')
            if og_img and og_img.get('content', '').startswith('http'):
                result['thumbnail'] = og_img['content']
                print(f"  ✅ og:image found: {result['thumbnail'][:60]}")

            # ── 2. twitter:image (fallback) ──────────────────────────────
            if not result.get('thumbnail'):
                tw_img = soup.find('meta', attrs={'name': 'twitter:image'})
                if tw_img and tw_img.get('content', '').startswith('http'):
                    result['thumbnail'] = tw_img['content']
                    print(f"  ✅ twitter:image found: {result['thumbnail'][:60]}")

            # ── 3. JSON-LD ───────────────────────────────────────────────
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    raw = script.string or script.get_text()
                    if not raw:
                        continue
                    data = json.loads(raw)
                    # JSON-LD can be a list or a single object
                    if isinstance(data, list):
                        data = next((d for d in data if d.get('@type') == 'Course'), data[0] if data else {})
                    if data.get('@type') != 'Course':
                        continue

                    # thumbnail from JSON-LD image
                    if not result.get('thumbnail'):
                        img = data.get('image')
                        if isinstance(img, str) and img.startswith('http'):
                            result['thumbnail'] = img
                        elif isinstance(img, dict) and img.get('url', '').startswith('http'):
                            result['thumbnail'] = img['url']

                    # title
                    if not result.get('title'):
                        result['title'] = data.get('name', '').strip()

                    # description
                    desc = data.get('description', '')
                    result['description'] = desc[:250] if desc else None

                    # instructor / author
                    author = data.get('author') or data.get('instructor')
                    if isinstance(author, list) and author:
                        author = author[0]
                    if isinstance(author, dict):
                        result['instructor'] = author.get('name')
                    elif isinstance(author, str):
                        result['instructor'] = author

                    # rating & students
                    agg = data.get('aggregateRating', {})
                    if agg:
                        result['rating'] = agg.get('ratingValue')
                        result['students'] = agg.get('ratingCount') or agg.get('reviewCount')

                    break   # found the Course block, stop looping
                except Exception:
                    continue

            # ── 4. __NEXT_DATA__ embedded JSON (Udemy React app) ─────────
            if not result.get('thumbnail') or not result.get('instructor'):
                next_data_tag = soup.find('script', id='__NEXT_DATA__')
                if next_data_tag:
                    try:
                        nd = json.loads(next_data_tag.string or '')
                        # Navigate the nested structure
                        props = nd.get('props', {}).get('pageProps', {})
                        course_data = props.get('course', props.get('courseData', {}))

                        if not result.get('thumbnail'):
                            thumb = (
                                course_data.get('image_480x270')
                                or course_data.get('image_240x135')
                                or course_data.get('image_100x100')
                            )
                            if thumb and thumb.startswith('http'):
                                result['thumbnail'] = thumb

                        if not result.get('instructor'):
                            instructors = course_data.get('visible_instructors', [])
                            if instructors:
                                result['instructor'] = instructors[0].get('display_name')

                        if not result.get('rating'):
                            result['rating'] = course_data.get('rating')

                        if not result.get('students'):
                            result['students'] = course_data.get('num_subscribers')
                    except Exception:
                        pass

            # ── 5. img tag with udemyassets CDN ─────────────────────────
            if not result.get('thumbnail'):
                for img in soup.find_all('img'):
                    src = img.get('src', '') or img.get('data-src', '')
                    if 'udemyassets' in src or 'udemy-images' in src:
                        if src.startswith('http'):
                            result['thumbnail'] = src
                            print(f"  ✅ img CDN found: {src[:60]}")
                            break

            if result.get('thumbnail'):
                return result

            print(f"  ❌ No thumbnail found for {clean_url}")
            return None

        except Exception as e:
            print(f"  ❌ Udemy meta fetch error: {e}")
            return None

    # ─────────────────────────────────────────────
    # BLOG POST THUMBNAIL (secondary fallback)
    # ─────────────────────────────────────────────

    def extract_scraped_thumbnail(self, html, title):
        """Extract thumbnail from blog post HTML as secondary fallback."""
        if not html:
            return None
        soup = BeautifulSoup(html, 'lxml')

        # og:image is most reliable
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content', '').startswith('http'):
            src = og_img['content']
            if any(x in src for x in ['udemy', 'cdn', 'udemyassets', 'img-c']):
                return src

        # Large images in article body
        for img in soup.find_all('img'):
            src = img.get('data-src') or img.get('src', '')
            if any(x in src.lower() for x in ['udemy', 'course', '480x270', '240x135', 'udemyassets']):
                if src.startswith('http') and not src.endswith('.svg'):
                    return src

        # Alt-text hints
        for img in soup.find_all('img', alt=re.compile('course|udemy', re.I)):
            src = img.get('data-src') or img.get('src', '')
            if src.startswith('http') and not src.endswith('.svg'):
                return src

        return None

    # ─────────────────────────────────────────────
    # PLACEHOLDER (last resort)
    # ─────────────────────────────────────────────

    def generate_placeholder(self, title, category):
        colors = {
            'programming': '3b82f6',
            'business':    '10b981',
            'design':      '8b5cf6',
            'data':        'f59e0b',
            'it':          'ef4444',
            'personal':    'ec4899',
            'general':     '6b7280',
        }
        color = colors.get(category, '6b7280')
        text  = urllib.parse.quote(title[:25])
        return f"https://via.placeholder.com/480x270/{color}/ffffff?text={text}"

    # ─────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────

    def check_coupon_valid(self, udemy_url):
        if not udemy_url or 'udemy.com' not in udemy_url:
            return True
        try:
            print(f"  Checking coupon...")
            resp = self.session.get(udemy_url, headers=UDEMY_HEADERS, timeout=15, allow_redirects=True)
            text_lower = resp.text.lower()
            expired_indicators = [
                'expired', 'no longer available', 'invalid coupon',
                'this coupon has expired', 'promotion expired',
                'the coupon code entered is not valid',
            ]
            if any(x in text_lower for x in expired_indicators):
                print(f"  ❌ EXPIRED")
                return False
            if 'buy now' in text_lower and '100% off' not in text_lower and 'free' not in text_lower:
                if resp.status_code == 200:
                    print(f"  ❌ NOT FREE")
                    return False
            print(f"  ✅ VALID")
            return True
        except Exception as e:
            print(f"  ⚠️ Check failed: {e}")
            return True

    def detect_category(self, title):
        t = title.lower()
        cats = {
            'programming': ['python', 'java', 'javascript', 'coding', 'programming',
                            'developer', 'web dev', 'html', 'css', 'react', 'node',
                            'django', 'sql', 'php', 'kotlin', 'android', 'ios',
                            'swift', 'c++', 'c#', 'go ', 'rust', 'angular', 'vue',
                            'typescript', 'flutter'],
            'business':    ['business', 'marketing', 'seo', 'entrepreneur', 'management',
                            'finance', 'accounting', 'sales', 'startup', 'leadership',
                            'mba', 'project management', 'agile', 'scrum'],
            'design':      ['design', 'photoshop', 'illustrator', 'ui', 'ux', 'graphic',
                            'drawing', 'figma', 'canva', 'adobe', 'blender', '3d',
                            'animation', 'video editing', 'premiere', 'after effects',
                            'davinci'],
            'data':        ['data science', 'machine learning', 'ml ', 'ai ', 'analytics',
                            'sql', 'excel', 'power bi', 'tableau', 'deep learning', 'nlp',
                            'artificial intelligence', 'pandas', 'numpy', 'tensorflow',
                            'pytorch'],
            'it':          ['aws', 'cloud', 'linux', 'networking', 'cybersecurity',
                            'hacking', 'comptia', 'cisco', 'devops', 'docker',
                            'kubernetes', 'azure', 'gcp', 'server', 'terraform',
                            'vault', 'certified', 'administrator'],
            'personal':    ['personal development', 'leadership', 'communication',
                            'productivity', 'time management', 'mindset', 'stress',
                            'meditation', 'public speaking'],
        }
        for cat, keywords in cats.items():
            if any(kw in t for kw in keywords):
                return cat
        return 'general'

    def extract_coupon(self, url):
        if not url or url == 'N/A':
            return 'UNKNOWN'
        match = re.search(r'[?&]couponCode?=([A-Za-z0-9_\-]+)', url)
        return match.group(1) if match else 'UNKNOWN'

    def add_course(self, title, url, source, post_html=None, category=None, price='$89.99'):
        if not title or title in self.seen_titles or len(title) < 10:
            return None
        title = re.sub(r'\s+', ' ', title).strip()
        self.seen_titles.add(title)

        cat           = category or self.detect_category(title)
        scraped_thumb = self.extract_scraped_thumbnail(post_html, title) if post_html else None

        course = {
            'title':            title,
            'url':              url if url else 'N/A',
            'coupon_code':      self.extract_coupon(url),
            'original_price':   price,
            'discount_price':   'Free',
            'discount_percent': '100%',
            'rating':           None,
            'students':         None,
            'category':         cat,
            'platform':         'Udemy',
            'source':           source,
            '_scraped_thumb':   scraped_thumb,   # temp, removed after enrichment
            'thumbnail':        None,
            'instructor':       None,
            'description':      None,
            'expires_at':       (datetime.now() + timedelta(days=3)).isoformat(),
            'scraped_at':       datetime.now().isoformat(),
        }
        self.courses.append(course)
        return course

    # ─────────────────────────────────────────────
    # ✅ ENRICHMENT — replaces broken oEmbed
    # ─────────────────────────────────────────────

    def enrich_with_udemy_pages(self):
        """
        Visit each Udemy course page to extract:
          - Real thumbnail (og:image / twitter:image / JSON-LD / __NEXT_DATA__)
          - Instructor name
          - Rating & student count
          - Short description

        Falls back to blog-scraped image, then placeholder.
        """
        print(f"\n{'='*60}")
        print("ENRICHING COURSES WITH UDEMY PAGE DATA")
        print(f"{'='*60}")

        stats = {'udemy_page': 0, 'blog_scraped': 0, 'placeholder': 0}

        for i, course in enumerate(self.courses, 1):
            url = course.get('url', '')
            print(f"\n[{i}/{len(self.courses)}] {course['title'][:55]}...")

            if 'udemy.com/course/' in url:
                meta = self.get_udemy_course_meta(url)
                if meta and meta.get('thumbnail'):
                    # Prefer oEmbed title if it's richer
                    if meta.get('title') and len(meta['title']) > 10:
                        course['title'] = meta['title']
                    course['thumbnail']   = meta['thumbnail']
                    course['instructor']  = meta.get('instructor')
                    course['description'] = meta.get('description')
                    if meta.get('rating'):
                        course['rating'] = float(meta['rating'])
                    if meta.get('students'):
                        course['students'] = meta['students']
                    stats['udemy_page'] += 1
                    time.sleep(self.udemy_delay)
                    continue

            # Fallback 1: thumbnail scraped from the coupon blog post
            blog_thumb = course.pop('_scraped_thumb', None)
            if blog_thumb:
                course['thumbnail'] = blog_thumb
                stats['blog_scraped'] += 1
                print(f"  ⚠️  Using blog-scraped thumbnail")
                continue

            # Fallback 2: generated placeholder
            course['thumbnail'] = self.generate_placeholder(course['title'], course['category'])
            stats['placeholder'] += 1
            print(f"  🖼️  Using placeholder")

        # Remove temp field from any remaining courses
        for course in self.courses:
            course.pop('_scraped_thumb', None)

        print(f"\n✅ Udemy page: {stats['udemy_page']} | "
              f"⚠️ Blog scraped: {stats['blog_scraped']} | "
              f"🖼️ Placeholder: {stats['placeholder']}")
        return stats

    # ─────────────────────────────────────────────
    # COUPON VALIDATION
    # ─────────────────────────────────────────────

    def filter_expired(self, max_check=25):
        print(f"\n{'='*60}")
        print("CHECKING COUPON VALIDITY")
        print(f"{'='*60}")

        valid      = []
        expired    = []
        check_queue = [c for c in self.courses if c['coupon_code'] != 'UNKNOWN'][:max_check]
        unchecked  = [c for c in self.courses if c not in check_queue]

        for course in check_queue:
            if self.check_coupon_valid(course['url']):
                valid.append(course)
            else:
                expired.append(course)

        valid.extend(unchecked)
        print(f"\n✅ Valid: {len(valid)} | ❌ Expired: {len(expired)} | ⏭️ Unchecked: {len(unchecked)}")
        if expired:
            print("Expired courses removed:")
            for c in expired[:5]:
                print(f"  - {c['title'][:55]}...")
        self.courses = valid
        return len(expired)

    # ─────────────────────────────────────────────
    # SOURCES
    # ─────────────────────────────────────────────

    def scrape_udemyfree_eu(self):
        print("\n[Source 1] udemyfree.eu.org")
        html = self.fetch('https://udemyfree.eu.org/')
        if not html:
            return 0
        soup  = BeautifulSoup(html, 'lxml')
        articles = soup.find_all('article')
        print(f"  Found {len(articles)} articles")
        count = 0
        for article in articles:
            title_tag = article.find(['h2', 'h3'])
            if not title_tag:
                continue
            link      = title_tag.find('a')
            title     = title_tag.get_text(strip=True)
            post_url  = link['href'] if link else 'N/A'
            post_html = udemy_url = None

            if post_url and post_url != 'N/A':
                post_html = self.fetch(post_url)
                if post_html:
                    ps = BeautifulSoup(post_html, 'lxml')
                    for a in ps.find_all('a', href=True):
                        if 'udemy.com/course/' in a['href']:
                            udemy_url = a['href']
                            break

            if self.add_course(title, udemy_url or 'N/A', 'UdemyFree.eu.org', post_html):
                count += 1
        return count

    def scrape_udemyfreecourses_eu(self):
        print("\n[Source 2] udemyfreecourses.eu.org")
        html = self.fetch('https://www.udemyfreecourses.eu.org/')
        if not html:
            return 0
        soup     = BeautifulSoup(html, 'lxml')
        articles = soup.find_all('article') or soup.find_all('div', class_=re.compile('post|entry'))
        print(f"  Found {len(articles)} articles")
        count = 0
        for article in articles:
            title_tag = article.find(['h2', 'h3']) or article.find('a')
            if not title_tag:
                continue
            title    = title_tag.get_text(strip=True)
            link     = title_tag if title_tag.name == 'a' else title_tag.find('a')
            post_url = link['href'] if link and link.has_attr('href') else 'N/A'
            if post_url.startswith('/'):
                post_url = 'https://www.udemyfreecourses.eu.org' + post_url
            post_html = udemy_url = None

            if post_url and post_url != 'N/A' and 'udemy.com' not in post_url:
                post_html = self.fetch(post_url)
                if post_html:
                    ps = BeautifulSoup(post_html, 'lxml')
                    for a in ps.find_all('a', href=True):
                        if 'udemy.com/course/' in a['href']:
                            udemy_url = a['href']
                            break

            if self.add_course(title, udemy_url or post_url, 'UdemyFreeCourses.eu.org', post_html):
                count += 1
        return count

    def scrape_coursecouponclub(self, max_pages=5):
        print(f"\n[Source 3] coursecouponclub.com (up to {max_pages} pages)")
        count = 0
        for page in range(1, max_pages + 1):
            url  = 'https://coursecouponclub.com/' if page == 1 else f'https://coursecouponclub.com/page/{page}/'
            html = self.fetch(url)
            if not html:
                continue
            soup  = BeautifulSoup(html, 'lxml')
            items = (
                soup.find_all('article') or
                soup.find_all('div', class_=re.compile('product|course|card|post')) or
                soup.find_all('li',  class_=re.compile('product|course'))
            )
            print(f"  Page {page}: Found {len(items)} items")
            if not items:
                break

            for item in items:
                title_tag = (
                    item.find(['h2', 'h3', 'h4']) or
                    item.find('a', class_=re.compile('title')) or
                    item.find('div', class_=re.compile('title'))
                )
                if not title_tag:
                    if item.name == 'a':
                        title_tag = item
                    else:
                        continue

                title    = title_tag.get_text(strip=True)
                link     = title_tag if title_tag.name == 'a' else title_tag.find('a')
                post_url = link['href'] if link and link.has_attr('href') else 'N/A'
                post_html = udemy_url = None

                if post_url and post_url != 'N/A' and 'udemy.com' not in post_url:
                    post_html = self.fetch(post_url)
                    if post_html:
                        ps = BeautifulSoup(post_html, 'lxml')
                        for a in ps.find_all('a', href=True):
                            if 'udemy.com/course/' in a['href']:
                                udemy_url = a['href']
                                break

                if self.add_course(title, udemy_url or post_url, 'CourseCouponClub.com', post_html):
                    count += 1
            time.sleep(1)
        return count

    def scrape_couponscorpion(self, max_pages=3):
        print(f"\n[Source 4] couponscorpion.com (up to {max_pages} pages)")
        count = 0
        for page in range(1, max_pages + 1):
            url  = 'https://couponscorpion.com/' if page == 1 else f'https://couponscorpion.com/page/{page}/'
            html = self.fetch(url)
            if not html:
                continue
            soup  = BeautifulSoup(html, 'lxml')
            items = soup.find_all('article') or soup.find_all('div', class_=re.compile('course|post|card|item'))
            print(f"  Page {page}: Found {len(items)} items")
            if not items:
                break

            for item in items:
                title_tag = item.find(['h2', 'h3', 'h4', 'h5']) or item.find('a')
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if len(title) < 10 or 'FAQ' in title or 'How to' in title:
                    continue
                link     = title_tag if title_tag.name == 'a' else title_tag.find('a')
                post_url = link['href'] if link and link.has_attr('href') else 'N/A'
                post_html = udemy_url = None

                if post_url and post_url != 'N/A':
                    if 'udemy.com' in post_url:
                        udemy_url = post_url
                    else:
                        post_html = self.fetch(post_url)
                        if post_html:
                            ps = BeautifulSoup(post_html, 'lxml')
                            for a in ps.find_all('a', href=True):
                                if 'udemy.com/course/' in a['href']:
                                    udemy_url = a['href']
                                    break

                if self.add_course(title, udemy_url or post_url, 'CouponScorpion.com', post_html):
                    count += 1
            time.sleep(1)
        return count

    # ─────────────────────────────────────────────
    # MAIN RUNNER
    # ─────────────────────────────────────────────

    def run(self):
        print(f"{'='*60}")
        print("ULTIMATE UDEMY SCRAPER  v2")
        print("Features: Direct-page Thumbnails + Expired Cleanup")
        print(f"{'='*60}")

        results = {
            'udemyfree.eu':      self.scrape_udemyfree_eu(),
            'udemyfreecourses.eu': self.scrape_udemyfreecourses_eu(),
            'coursecouponclub':  self.scrape_coursecouponclub(max_pages=5),
            'couponscorpion':    self.scrape_couponscorpion(max_pages=3),
        }

        # Enrich with real thumbnails from Udemy pages
        thumb_stats = self.enrich_with_udemy_pages()

        # Remove expired coupons
        expired_count = self.filter_expired(max_check=25)

        # ── Stats ─────────────────────────────────────────────────────────
        by_cat = {}
        for c in self.courses:
            by_cat.setdefault(c['category'], []).append(c)

        print(f"\n{'='*60}")
        print("FINAL RESULTS")
        print(f"{'='*60}")
        print(f"Total courses   : {len(self.courses)}")
        print(f"Expired removed : {expired_count}")
        print(f"\nThumbnail sources:")
        print(f"  🎨 Udemy page : {thumb_stats['udemy_page']}")
        print(f"  📷 Blog post  : {thumb_stats['blog_scraped']}")
        print(f"  🖼️  Placeholder: {thumb_stats['placeholder']}")
        print(f"\nBy category:")
        for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            bar = "█" * min(len(items), 20)
            print(f"  {cat:15} | {len(items):3} | {bar}")

        # ── Save ──────────────────────────────────────────────────────────
        output = {
            "meta": {
                "scraped_at":        datetime.now().isoformat(),
                "next_update":       (datetime.now() + timedelta(days=1)).isoformat(),
                "total_courses":     len(self.courses),
                "expired_removed":   expired_count,
                "thumbnail_sources": thumb_stats,
                "sources":           list(results.keys()),
                "source_counts":     results,
            },
            "courses":     self.courses,
            "by_category": {k: v for k, v in by_cat.items()},
        }

        with open('udemy_deals.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"\n💾 Saved to: udemy_deals.json")
        print("Done! ✅")
        return self.courses


if __name__ == '__main__':
    scraper = UltimateUdemyScraper()
    scraper.run()
