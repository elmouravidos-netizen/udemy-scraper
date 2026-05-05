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

class UltimateUdemyScraper:
    def __init__(self):
        self.courses = []
        self.seen_titles = set()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.oembed_delay = 1.2  # Seconds between oEmbed calls
    
    def fetch(self, url, retries=2):
        for attempt in range(retries):
            try:
                print(f"    Fetching: {url[:65]}...")
                resp = self.session.get(url, timeout=20)
                resp.raise_for_status()
                return resp.text
            except Exception as e:
                print(f"    Error: {e}")
                if attempt < retries - 1:
                    time.sleep(1)
        return None
    
    def get_udemy_oembed(self, udemy_url):
        """Fetch real thumbnail, title, instructor from Udemy oEmbed API"""
        if not udemy_url or 'udemy.com/course/' not in udemy_url:
            return None
        
        try:
            encoded_url = urllib.parse.quote(udemy_url, safe='')
            api_url = f"https://www.udemy.com/api-2.0/structured-data/oembed/?url={encoded_url}"
            
            print(f"      oEmbed: {udemy_url[:50]}...")
            resp = self.session.get(api_url, timeout=15, headers=HEADERS)
            
            if resp.status_code != 200:
                print(f"      oEmbed status: {resp.status_code}")
                return None
            
            data = resp.json()
            
            result = {
                'thumbnail': data.get('thumbnail_url'),
                'title': data.get('title'),
                'instructor': data.get('author_name'),
                'description': data.get('description', '')[:250] if data.get('description') else None
            }
            
            # Validate thumbnail URL
            if result['thumbnail'] and not result['thumbnail'].startswith('http'):
                result['thumbnail'] = None
            
            print(f"      ✅ Got thumbnail: {result['thumbnail'][:60] if result['thumbnail'] else 'None'}")
            return result
            
        except Exception as e:
            print(f"      oEmbed failed: {e}")
            return None
    
    def extract_scraped_thumbnail(self, html, title):
        """Extract thumbnail from blog post HTML"""
        if not html:
            return None
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Strategy 1: og:image meta tag (most reliable)
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            src = og_img['content']
            if 'udemy' in src or 'cdn' in src:
                return src
        
        # Strategy 2: First large image in article
        for img in soup.find_all('img'):
            src = img.get('data-src') or img.get('src', '')
            if any(x in src.lower() for x in ['udemy', 'course', '480x270', '240x135']):
                if src.startswith('http'):
                    return src
        
        # Strategy 3: Any image with course-related alt
        for img in soup.find_all('img', alt=re.compile('course|udemy', re.I)):
            src = img.get('data-src') or img.get('src', '')
            if src.startswith('http') and not src.endswith('.svg'):
                return src
        
        return None
    
    def generate_placeholder(self, title, category):
        """Generate a colored placeholder with category name"""
        colors = {
            'programming': '3b82f6',  # blue
            'business': '10b981',     # green
            'design': '8b5cf6',       # purple
            'data': 'f59e0b',         # amber
            'it': 'ef4444',           # red
            'personal': 'ec4899',     # pink
            'general': '6b7280'       # gray
        }
        color = colors.get(category, '6b7280')
        text = urllib.parse.quote(title[:25])
        return f"https://via.placeholder.com/480x270/{color}/ffffff?text={text}"
    
    def check_coupon_valid(self, udemy_url):
        """Check if Udemy coupon is still active"""
        if not udemy_url or 'udemy.com' not in udemy_url:
            return True
        
        try:
            print(f"      Checking coupon...")
            resp = self.session.get(udemy_url, headers=HEADERS, timeout=15, allow_redirects=True)
            text_lower = resp.text.lower()
            
            expired_indicators = [
                'expired', 'no longer available', 'invalid coupon',
                'this coupon has expired', 'promotion expired',
                'the coupon code entered is not valid'
            ]
            
            if any(x in text_lower for x in expired_indicators):
                print(f"      ❌ EXPIRED")
                return False
            
            # Check if price is shown without discount
            if 'buy now' in text_lower and '100% off' not in text_lower and 'free' not in text_lower:
                if resp.status_code == 200:
                    print(f"      ❌ NOT FREE")
                    return False
            
            print(f"      ✅ VALID")
            return True
            
        except Exception as e:
            print(f"      ⚠️ Check failed: {e}")
            return True
    
    def detect_category(self, title):
        t = title.lower()
        cats = {
            'programming': ['python', 'java', 'javascript', 'coding', 'programming', 'developer', 'web dev', 'html', 'css', 'react', 'node', 'django', 'sql', 'php', 'kotlin', 'android', 'ios', 'swift', 'c++', 'c#', 'go ', 'rust', 'angular', 'vue', 'typescript', 'flutter'],
            'business': ['business', 'marketing', 'seo', 'entrepreneur', 'management', 'finance', 'accounting', 'sales', 'startup', 'leadership', 'mba', 'project management', 'agile', 'scrum'],
            'design': ['design', 'photoshop', 'illustrator', 'ui', 'ux', 'graphic', 'drawing', 'figma', 'canva', 'adobe', 'blender', '3d', 'animation', 'video editing', 'premiere', 'after effects', 'davinci'],
            'data': ['data science', 'machine learning', 'ml ', 'ai ', 'analytics', 'sql', 'excel', 'power bi', 'tableau', 'deep learning', 'nlp', 'artificial intelligence', 'pandas', 'numpy', 'tensorflow', 'pytorch'],
            'it': ['aws', 'cloud', 'linux', 'networking', 'cybersecurity', 'hacking', 'comptia', 'cisco', 'devops', 'docker', 'kubernetes', 'azure', 'gcp', 'server', 'terraform', 'vault', 'certified', 'administrator'],
            'personal': ['personal development', 'leadership', 'communication', 'productivity', 'time management', 'mindset', 'stress', 'meditation', 'public speaking'],
        }
        for cat, keywords in cats.items():
            if any(kw in t for kw in keywords):
                return cat
        return 'general'
    
    def extract_coupon(self, url):
        if not url or url == 'N/A':
            return 'UNKNOWN'
        match = re.search(r'[?&]couponCode?=([A-Za-z0-9_]+)', url)
        return match.group(1) if match else 'UNKNOWN'
    
    def add_course(self, title, url, source, post_html=None, category=None, price='$89.99'):
        if not title or title in self.seen_titles or len(title) < 10:
            return None
        
        title = re.sub(r'\s+', ' ', title).strip()
        self.seen_titles.add(title)
        cat = category or self.detect_category(title)
        
        # Extract thumbnail from post HTML first (fallback)
        scraped_thumb = self.extract_scraped_thumbnail(post_html, title) if post_html else None
        
        # Build course object
        course = {
            'title': title,
            'url': url if url else 'N/A',
            'coupon_code': self.extract_coupon(url),
            'original_price': price,
            'discount_price': 'Free',
            'discount_percent': '100%',
            'rating': 4.0,
            'students': 'N/A',
            'category': cat,
            'platform': 'Udemy',
            'source': source,
            'thumbnail_scraped': scraped_thumb,
            'thumbnail': None,  # Will be filled by oEmbed
            'instructor': None,
            'description': None,
            'expires_at': (datetime.now() + timedelta(days=3)).isoformat(),
            'scraped_at': datetime.now().isoformat()
        }
        
        self.courses.append(course)
        return course
    
    def enrich_with_oembed(self):
        """Add real thumbnails via Udemy oEmbed API"""
        print(f"\n{'='*60}")
        print("ENRICHING WITH UDEMY OEMBED API")
        print(f"{'='*60}")
        
        enriched = 0
        failed = 0
        
        for course in self.courses:
            if 'udemy.com' not in course['url']:
                continue
            
            meta = self.get_udemy_oembed(course['url'])
            
            if meta:
                # Use oEmbed title if better
                if meta.get('title') and len(meta['title']) > 10:
                    course['title'] = meta['title']
                
                course['thumbnail'] = meta.get('thumbnail') or course['thumbnail_scraped']
                course['instructor'] = meta.get('instructor')
                course['description'] = meta.get('description')
                enriched += 1
            else:
                # Fallback to scraped thumbnail
                course['thumbnail'] = course['thumbnail_scraped']
                failed += 1
            
            # Final fallback: placeholder
            if not course['thumbnail']:
                course['thumbnail'] = self.generate_placeholder(course['title'], course['category'])
            
            # Clean up temp field
            course.pop('thumbnail_scraped', None)
            
            time.sleep(self.oembed_delay)
        
        print(f"\n✅ Enriched: {enriched} | ⚠️ Fallback: {failed} | 📊 Total: {len(self.courses)}")
    
    def filter_expired(self, max_check=25):
        """Remove courses with expired coupons"""
        print(f"\n{'='*60}")
        print("CHECKING COUPON VALIDITY")
        print(f"{'='*60}")
        
        valid = []
        expired = []
        
        check_queue = [c for c in self.courses if c['coupon_code'] != 'UNKNOWN'][:max_check]
        unchecked = [c for c in self.courses if c not in check_queue]
        
        for course in check_queue:
            is_valid = self.check_coupon_valid(course['url'])
            if is_valid:
                valid.append(course)
            else:
                expired.append(course)
        
        valid.extend(unchecked)
        
        print(f"\n✅ Valid: {len(valid)} | ❌ Expired: {len(expired)} | ⏭️ Unchecked: {len(unchecked)}")
        
        if expired:
            print("\nExpired courses removed:")
            for c in expired[:5]:
                print(f"  - {c['title'][:50]}...")
        
        self.courses = valid
        return len(expired)
    
    # ==================== SOURCES ====================
    
    def scrape_udemyfree_eu(self):
        print("\n[Source 1] udemyfree.eu.org")
        html = self.fetch('https://udemyfree.eu.org/')
        if not html:
            return 0
        
        soup = BeautifulSoup(html, 'lxml')
        articles = soup.find_all('article')
        print(f"  Found {len(articles)} articles")
        
        count = 0
        for article in articles:
            title_tag = article.find(['h2', 'h3'])
            if not title_tag:
                continue
            
            link = title_tag.find('a')
            title = title_tag.get_text(strip=True)
            post_url = link['href'] if link else 'N/A'
            
            post_html = None
            udemy_url = 'N/A'
            if post_url != 'N/A':
                post_html = self.fetch(post_url)
                if post_html:
                    post_soup = BeautifulSoup(post_html, 'lxml')
                    for a in post_soup.find_all('a', href=True):
                        if 'udemy.com/course/' in a['href']:
                            udemy_url = a['href']
                            break
            
            if self.add_course(title, udemy_url, 'UdemyFree.eu.org', post_html):
                count += 1
        return count
    
    def scrape_udemyfreecourses_eu(self):
        print("\n[Source 2] udemyfreecourses.eu.org")
        html = self.fetch('https://www.udemyfreecourses.eu.org/')
        if not html:
            return 0
        
        soup = BeautifulSoup(html, 'lxml')
        articles = soup.find_all('article') or soup.find_all('div', class_=re.compile('post|entry'))
        print(f"  Found {len(articles)} articles")
        
        count = 0
        for article in articles:
            title_tag = article.find(['h2', 'h3']) or article.find('a')
            if not title_tag:
                continue
            
            title = title_tag.get_text(strip=True)
            link = title_tag if title_tag.name == 'a' else title_tag.find('a')
            post_url = link['href'] if link and link.has_attr('href') else 'N/A'
            
            if post_url.startswith('/'):
                post_url = 'https://www.udemyfreecourses.eu.org' + post_url
            
            post_html = None
            udemy_url = 'N/A'
            if post_url != 'N/A' and 'udemy.com' not in post_url:
                post_html = self.fetch(post_url)
                if post_html:
                    post_soup = BeautifulSoup(post_html, 'lxml')
                    for a in post_soup.find_all('a', href=True):
                        if 'udemy.com/course/' in a['href']:
                            udemy_url = a['href']
                            break
            
            if self.add_course(title, udemy_url if udemy_url != 'N/A' else post_url, 'UdemyFreeCourses.eu.org', post_html):
                count += 1
        return count
    
    def scrape_coursecouponclub(self, max_pages=5):
        print(f"\n[Source 3] coursecouponclub.com (up to {max_pages} pages)")
        count = 0
        
        for page in range(1, max_pages + 1):
            url = 'https://coursecouponclub.com/' if page == 1 else f'https://coursecouponclub.com/page/{page}/'
            html = self.fetch(url)
            if not html:
                continue
            
            soup = BeautifulSoup(html, 'lxml')
            items = (
                soup.find_all('article') or
                soup.find_all('div', class_=re.compile('product|course|card|post')) or
                soup.find_all('li', class_=re.compile('product|course'))
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
                
                title = title_tag.get_text(strip=True)
                link = title_tag if title_tag.name == 'a' else title_tag.find('a')
                post_url = link['href'] if link and link.has_attr('href') else 'N/A'
                
                post_html = None
                udemy_url = 'N/A'
                if post_url != 'N/A' and 'udemy.com' not in post_url:
                    post_html = self.fetch(post_url)
                    if post_html:
                        post_soup = BeautifulSoup(post_html, 'lxml')
                        for a in post_soup.find_all('a', href=True):
                            if 'udemy.com/course/' in a['href']:
                                udemy_url = a['href']
                                break
                
                if self.add_course(title, udemy_url if udemy_url != 'N/A' else post_url, 'CourseCouponClub.com', post_html):
                    count += 1
            
            time.sleep(1)
        
        return count
    
    def scrape_couponscorpion(self, max_pages=3):
        print(f"\n[Source 4] couponscorpion.com (up to {max_pages} pages)")
        count = 0
        
        for page in range(1, max_pages + 1):
            url = 'https://couponscorpion.com/' if page == 1 else f'https://couponscorpion.com/page/{page}/'
            html = self.fetch(url)
            if not html:
                continue
            
            soup = BeautifulSoup(html, 'lxml')
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
                
                link = title_tag if title_tag.name == 'a' else title_tag.find('a')
                post_url = link['href'] if link and link.has_attr('href') else 'N/A'
                
                post_html = None
                udemy_url = 'N/A'
                if post_url != 'N/A':
                    if 'udemy.com' in post_url:
                        udemy_url = post_url
                    else:
                        post_html = self.fetch(post_url)
                        if post_html:
                            post_soup = BeautifulSoup(post_html, 'lxml')
                            for a in post_soup.find_all('a', href=True):
                                if 'udemy.com/course/' in a['href']:
                                    udemy_url = a['href']
                                    break
                
                if self.add_course(title, udemy_url if udemy_url != 'N/A' else post_url, 'CouponScorpion.com', post_html):
                    count += 1
            
            time.sleep(1)
        
        return count
    
    # ==================== MAIN ====================
    
    def run(self):
        print(f"{'='*60}")
        print("ULTIMATE UDEMY SCRAPER")
        print("Features: oEmbed Thumbnails + Expired Cleanup")
        print(f"{'='*60}")
        
        results = {}
        results['udemyfree.eu'] = self.scrape_udemyfree_eu()
        results['udemyfreecourses.eu'] = self.scrape_udemyfreecourses_eu()
        results['coursecouponclub'] = self.scrape_coursecouponclub(max_pages=5)
        results['couponscorpion'] = self.scrape_couponscorpion(max_pages=3)
        
        # Enrich with real thumbnails
        self.enrich_with_oembed()
        
        # Remove expired
        expired_count = self.filter_expired(max_check=25)
        
        # Stats
        by_cat = {}
        thumb_sources = {'oembed': 0, 'scraped': 0, 'placeholder': 0}
        
        for c in self.courses:
            by_cat.setdefault(c['category'], []).append(c)
            if c.get('instructor'):
                thumb_sources['oembed'] += 1
            elif 'via.placeholder' in (c.get('thumbnail') or ''):
                thumb_sources['placeholder'] += 1
            else:
                thumb_sources['scraped'] += 1
        
        print(f"\n{'='*60}")
        print(f"FINAL RESULTS")
        print(f"{'='*60}")
        print(f"Total courses: {len(self.courses)}")
        print(f"Expired removed: {expired_count}")
        print(f"\nThumbnails:")
        print(f"  🎨 oEmbed (real): {thumb_sources['oembed']}")
        print(f"  📷 Scraped: {thumb_sources['scraped']}")
        print(f"  🖼️ Placeholder: {thumb_sources['placeholder']}")
        
        for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            bar = "█" * min(len(items), 20)
            print(f"  {cat:15} | {len(items):3} | {bar}")
        
        # Save
        output = {
            "meta": {
                "scraped_at": datetime.now().isoformat(),
                "next_update": (datetime.now() + timedelta(days=1)).isoformat(),
                "total_courses": len(self.courses),
                "expired_removed": expired_count,
                "thumbnail_sources": thumb_sources,
                "sources": list(results.keys()),
                "source_counts": results
            },
            "courses": self.courses,
            "by_category": by_cat
        }
        
        with open('udemy_deals.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Saved to: udemy_deals.json")
        print("Done!")
        return self.courses


if __name__ == '__main__':
    scraper = UltimateUdemyScraper()
    scraper.run()
