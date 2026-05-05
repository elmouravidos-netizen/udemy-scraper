import requests
from bs4 import BeautifulSoup
import json
from datetime import datetime
import re
import time

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
    
    def detect_category(self, title):
        t = title.lower()
        cats = {
            'programming': ['python', 'java', 'javascript', 'coding', 'programming', 'developer', 'web dev', 'html', 'css', 'react', 'node', 'django', 'sql', 'php', 'kotlin', 'android', 'ios', 'swift', 'c++', 'c#', 'go ', 'rust', 'angular', 'vue', 'typescript'],
            'business': ['business', 'marketing', 'seo', 'entrepreneur', 'management', 'finance', 'accounting', 'sales', 'startup', 'leadership', 'mba', 'project management', 'agile', 'scrum'],
            'design': ['design', 'photoshop', 'illustrator', 'ui', 'ux', 'graphic', 'drawing', 'figma', 'canva', 'adobe', 'blender', '3d', 'animation', 'video editing', 'premiere', 'after effects'],
            'data': ['data science', 'machine learning', 'ml ', 'ai ', 'analytics', 'sql', 'excel', 'power bi', 'tableau', 'deep learning', 'nlp', 'artificial intelligence', 'pandas', 'numpy', 'tensorflow', 'pytorch'],
            'it': ['aws', 'cloud', 'linux', 'networking', 'cybersecurity', 'hacking', 'comptia', 'cisco', 'devops', 'docker', 'kubernetes', 'azure', 'gcp', 'server', 'terraform', 'vault', 'certified'],
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
        """Add course with deduplication"""
        if not title or title in self.seen_titles or len(title) < 10:
            return False
        
        # Clean title
        title = re.sub(r'\s+', ' ', title).strip()
        
        self.seen_titles.add(title)
        cat = category or self.detect_category(title)
        
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
            'scraped_at': datetime.now().isoformat()
        })
        return True
    
    # ============ SOURCE 1: udemyfree.eu.org ============
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
            
            # Follow to get Udemy URL
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
    
    # ============ SOURCE 2: udemyfreecourses.eu.org ============
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
    
    # ============ SOURCE 3: coursecouponclub.com WITH PAGINATION ============
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
            
            # Try multiple selectors - this site uses product-style cards
            items = (
                soup.find_all('article') or
                soup.find_all('div', class_=re.compile('product|course|card|post')) or
                soup.find_all('li', class_=re.compile('product|course')) or
                soup.select('.astra-shop-summary-wrap') or
                soup.select('.woocommerce-loop-product__title')
            )
            
            print(f"  Page {page}: Found {len(items)} items")
            
            if not items:
                break  # No more pages
            
            for item in items:
                # Try multiple title selectors
                title_tag = (
                    item.find(['h2', 'h3', 'h4']) or
                    item.find('a', class_=re.compile('title')) or
                    item.find('div', class_=re.compile('title')) or
                    item.find('span', class_=re.compile('title'))
                )
                
                if not title_tag:
                    # Sometimes title is in the item itself if it's an <a>
                    if item.name == 'a':
                        title_tag = item
                    else:
                        continue
                
                title = title_tag.get_text(strip=True)
                
                # Find link
                link = title_tag if title_tag.name == 'a' else title_tag.find('a')
                post_url = link['href'] if link and link.has_attr('href') else 'N/A'
                
                # Get Udemy URL from post page
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
            
            time.sleep(1)  # Be polite
        
        return count
    
    # ============ SOURCE 4: couponscorpion.com ============
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
            
            # CouponScorpion uses various card layouts
            items = (
                soup.find_all('article') or
                soup.find_all('div', class_=re.compile('course|post|card|item')) or
                soup.select('.elementor-post') or
                soup.find_all('div', class_=re.compile('elementor'))
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
                
                # Try to extract coupon from URL
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
    
    # ============ SOURCE 5: real.discount ============
    def scrape_realdiscount(self):
        print("\n[Source 5] real.discount")
        count = 0
        
        # Try homepage first
        html = self.fetch('https://www.real.discount/')
        if not html:
            return 0
        
        soup = BeautifulSoup(html, 'lxml')
        
        # Real.discount might use app-style cards or standard blog cards
        items = (
            soup.find_all('div', class_=re.compile('course|card')) or
            soup.find_all('article') or
            soup.find_all('a', href=re.compile('udemy|course'))
        )
        
        print(f"  Found {len(items)} potential items")
        
        for item in items:
            if item.name == 'a' and item.has_attr('href'):
                title = item.get_text(strip=True)
                url = item['href']
                if 'udemy.com' in url and len(title) > 10:
                    if self.add_course(title, url, 'Real.Discount'):
                        count += 1
            else:
                title_tag = item.find(['h2', 'h3', 'h4']) or item.find('a')
                if not title_tag:
                    continue
                
                title = title_tag.get_text(strip=True)
                link = title_tag if title_tag.name == 'a' else title_tag.find('a')
                url = link['href'] if link and link.has_attr('href') else 'N/A'
                
                if len(title) > 10 and ('udemy.com' in url or 'real.discount' in url):
                    if self.add_course(title, url, 'Real.Discount'):
                        count += 1
        
        return count
    
    # ============ MAIN RUNNER ============
    def run(self):
        print("=" * 60)
        print("ULTIMATE UDEMY SCRAPER - Target: 50-100+ Courses")
        print("=" * 60)
        
        results = {}
        results['udemyfree.eu'] = self.scrape_udemyfree_eu()
        results['udemyfreecourses.eu'] = self.scrape_udemyfreecourses_eu()
        results['coursecouponclub'] = self.scrape_coursecouponclub(max_pages=5)
        results['couponscorpion'] = self.scrape_couponscorpion(max_pages=3)
        results['realdiscount'] = self.scrape_realdiscount()
        
        # Stats
        by_cat = {}
        for c in self.courses:
            by_cat.setdefault(c['category'], []).append(c)
        
        print("\n" + "=" * 60)
        print(f"GRAND TOTAL: {len(self.courses)} UNIQUE COURSES")
        print("=" * 60)
        print("By Source:")
        for src, count in results.items():
            print(f"  {src:25} | {count:3} courses")
        print("\nBy Category:")
        for cat, items in sorted(by_cat.items(), key=lambda x: -len(x[1])):
            bar = "█" * min(len(items), 20)
            print(f"  {cat:15} | {len(items):3} courses | {bar}")
        
        # Save
        output = {
            "meta": {
                "scraped_at": datetime.now().isoformat(),
                "total_courses": len(self.courses),
                "sources": list(results.keys()),
                "source_counts": results
            },
            "courses": self.courses,
            "by_category": by_cat
        }
        
        with open('udemy_deals.json', 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"\nSaved to: udemy_deals.json")
        print("Done!")
        return self.courses


if __name__ == '__main__':
    scraper = UltimateUdemyScraper()
    scraper.run()