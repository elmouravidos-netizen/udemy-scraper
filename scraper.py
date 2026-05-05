import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime, timedelta
import re
import time

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
}

class UltimateUdemyScraper:
    def __init__(self):
        self.courses = []
        self.seen_titles = set()
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
    
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
    
    def check_coupon_valid(self, udemy_url):
        """Check if Udemy coupon is still active (100% off)"""
        if not udemy_url or udemy_url == 'N/A' or 'udemy.com' not in udemy_url:
            return True  # Can't check, assume valid
        
        try:
            print(f"      Checking coupon: {udemy_url[:60]}...")
            resp = self.session.get(udemy_url, headers=HEADERS, timeout=15, allow_redirects=True)
            
            # Check for expired indicators
            text_lower = resp.text.lower()
            if any(x in text_lower for x in ['expired', 'no longer available', 'invalid coupon', 'this coupon has expired']):
                print(f"      ❌ EXPIRED")
                return False
            if 'buy now' in text_lower and '100% off' not in text_lower and 'free' not in text_lower:
                print(f"      ❌ NOT FREE ANYMORE")
                return False
            
            print(f"      ✅ VALID")
            return True
        except Exception as e:
            print(f"      ⚠️ Check failed: {e}")
            return True  # Assume valid if check fails
    
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
    
    def add_course(self, title, url, source, category=None, price='$89.99'):
        if not title or title in self.seen_titles or len(title) < 10:
            return False
        
        title = re.sub(r'\s+', ' ', title).strip()
        self.seen_titles.add(title)
        cat = category or self.detect_category(title)
        
        # Set expiry: 3 days from now (typical coupon lifespan)
        expires_at = (datetime.now() + timedelta(days=3)).isoformat()
        
        self.courses.append({
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
            'expires_at': expires_at,
            'scraped_at': datetime.now().isoformat()
        })
        return True
    
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
            
            udemy_url = 'N/A'
            if post_url != 'N/A':
                post_html = self.fetch(post_url)
                if post_html:
                    post_soup = BeautifulSoup(post_html, 'lxml')
                    for a in post_soup.find_all('a', href=True):
                        if 'udemy.com/course/' in a['href']:
                            udemy_url = a['href']
                            break
            
            if self.add_course(title, udemy_url, 'UdemyFree.eu.org'):
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
            
            udemy_url = 'N/A'
            if post_url != 'N/A' and 'udemy.com' not in post_url:
                post_html = self.fetch(post_url)
                if post_html:
                    post_soup = BeautifulSoup(post_html, 'lxml')
                    for a in post_soup.find_all('a', href=True):
                        if 'udemy.com/course/' in a['href']:
                            udemy_url = a['href']
                            break
            
            if self.add_course(title, udemy_url if udemy_url != 'N/A' else post_url, 'UdemyFreeCourses.eu.org'):
                count += 1
        return count
    
    def scrape_coursecouponclub(self, max_pages=5):
        print(f"\n[Source 3] coursecouponclub.com (up to {max_pages} pages)")
        count = 0
        
        for page in range(1, max_pages + 1):
            if page == 1:
                url = 'https://coursecouponclub.com/'
            else:
                url = f'https://coursecouponclub.com/page/{page}/'
            
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
                
                udemy_url = 'N/A'
                if post_url != 'N/A' and 'udemy.com' not in post_url:
                    post_html = self.fetch(post_url)
                    if post_html:
                        post_soup = BeautifulSoup(post_html, 'lxml')
                        for a in post_soup.find_all('a', href=True):
                            if 'udemy.com/course/' in a['href']:
                                udemy_url = a['href']
                                break
                
                if self.add_course(title, udemy_url if udemy_url != 'N/A' else post_url, 'CourseCouponClub.com'):
                    count += 1
            
            time.sleep(1)
        
        return count
    
    def scrape_couponscorpion(self, max_pages=3):
        print(f"\n[Source 4] couponscorpion.com (up to {max_pages} pages)")
        count = 0
        
        for page in range(1, max_pages + 1):
            if page == 1:
                url = 'https://couponscorpion.com/'
            else:
                url = f'https://couponscorpion.com/page/{page}/'
            
            html = self.fetch(url)
            if not html:
                continue
            
            soup = BeautifulSoup(html, 'lxml')
            items = (
                soup.find_all('article') or
                soup.find_all('div', class_=re.compile('course|post|card|item'))
            )
            
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
                
                if self.add_course(title, udemy_url if udemy_url != 'N/A' else post_url, 'CouponScorpion.com'):
                    count += 1
            
            time.sleep(1)
        
        return count
    
    def filter_expired(self, max_check=30):
        """Remove courses with expired coupons"""
        print(f"\n{'='*60}")
        print("CHECKING COUPON VALIDITY")
        print(f"{'='*60}")
        
        valid = []
        expired = []
        
        # Prioritize checking courses with known coupons
        check_queue = [c for c in self.courses if c['coupon_code'] != 'UNKNOWN'][:max_check]
        
        for course in check_queue:
            is_valid = self.check_coupon_valid(course['url'])
            if is_valid:
                valid.append(course)
            else:
                expired.append(course)
        
        # Add unchecked courses (unknown coupons or beyond max_check)
        unchecked = [c for c in self.courses if c not in check_queue]
        valid.extend(unchecked)
        
        print(f"\n✅ Valid: {len(valid)} | ❌ Expired: {len(expired)} | ⏭️ Unchecked: {len(unchecked)}")
        
        if expired:
            print("\nExpired courses removed:")
            for c in expired[:5]:
                print(f"  - {c['title'][:50]}...")
        
        self.courses = valid
        return len(expired)
    
    def run(self):
        print(f"{'='*60}")
        print("ULTIMATE UDEMY SCRAPER - Auto-Cleanup Edition")
        print(f"{'='*60}")
        
        results = {}
        results['udemyfree.eu'] = self.scrape_udemyfree_eu()
        results['udemyfreecourses.eu'] = self.scrape_udemyfreecourses_eu()
        results['coursecouponclub'] = self.scrape_coursecouponclub(max_pages=5)
        results['couponscorpion'] = self.scrape_couponscorpion(max_pages=3)
        
        # Remove expired coupons
        expired_count = self.filter_expired(max_check=25)
        
        # Stats
        by_cat = {}
        for c in self.courses:
            by_cat.setdefault(c['category'], []).append(c)
        
        print(f"\n{'='*60}")
        print(f"FINAL RESULTS")
        print(f"{'='*60}")
        print(f"Total courses: {len(self.courses)}")
        print(f"Expired removed: {expired_count}")
        
        for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            bar = "█" * min(len(items), 20)
            print(f"  {cat:15} | {len(items):3} | {bar}")
        
        # Save
        output = {
            "meta": {
                "scraped_at": datetime.now().isoformat(),
                "expires_check": (datetime.now() + timedelta(days=1)).isoformat(),
                "total_courses": len(self.courses),
                "expired_removed": expired_count,
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
