import os
import json
import time
import random
import base64
import requests
import re
from datetime import datetime
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

# --- Configuration ---
BASE_URL = "https://codelist.cc/v3/"
PAGE_URL_TEMPLATE = "https://codelist.cc/pges/{}/"
DATA_DIR = "data_repo"  # Name of the subfolder where Data Repo is cloned
STATE_FILE = os.path.join(DATA_DIR, "state.json")
LOG_FILE = os.path.join(DATA_DIR, "logs.txt")
CHUNK_SIZE = 50

# Regex for common download mirrors
MIRROR_REGEX = re.compile(
    r'https?://(?:www\.)?(mega\.nz|mediafire\.com|gofile\.io|krakenfiles\.com|drop\.download|1fichier\.com|userscloud\.com|rapidgator\.net|katfile\.com|turbobit\.net|send\.cm|zippyshare\.com)/[^\s"\'<>]+'
)

ua = UserAgent()

def log(message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    print(message)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            try:
                return json.load(f)
            except:
                pass
    return {
        "current_page_index": 1,
        "last_scraped_url": None,
        "total_items_scraped": 0
    }

def save_state(state):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_image_base64(img_url):
    if not img_url:
        return None
    if img_url.startswith('/'):
        img_url = "https://codelist.cc" + img_url
    try:
        headers = {"User-Agent": ua.random}
        response = requests.get(img_url, headers=headers, timeout=10)
        if response.status_code == 200:
            content_length = len(response.content)
            if content_length < 150 * 1024: # < 150KB
                return base64.b64encode(response.content).decode('utf-8')
            else:
                log(f"Skipping image (too large: {content_length // 1024}KB): {img_url}")
    except Exception as e:
        log(f"Error downloading image {img_url}: {e}")
    return None

def scrape_post_details(post_url):
    try:
        headers = {"User-Agent": ua.random}
        response = requests.get(post_url, headers=headers, timeout=15)
        if response.status_code != 200:
            log(f"Failed to load post: {post_url} (Status: {response.status_code})")
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        title_tag = soup.select_one('h1.entry-title')
        title = title_tag.text.strip() if title_tag else "No Title"
        
        category = "Uncategorized"
        breadcrumb = soup.select('.over a')
        if len(breadcrumb) >= 2:
            category = breadcrumb[1].text.strip()
            
        date_tag = soup.select_one('time')
        date_str = date_tag.get('datetime') or date_tag.text.strip() if date_tag else str(datetime.now())
        
        # Deep-link extraction using regex on the whole Page Text/HTML
        full_links = list(set(re.findall(r'https?://(?:www\.)?(?:mega\.nz|mediafire\.com|gofile\.io|krakenfiles\.com|drop\.download|1fichier\.com|userscloud\.com|rapidgator\.net|katfile\.com|turbobit\.net|send\.cm|zippyshare\.com)/[^\s"\'<>]+', response.text)))

        # Find thumbnail within the post content or header
        img_tag = soup.select_one('.post__thumb img') or soup.select_one('article img')
        img_url = img_tag.get('src') if img_tag else None
        image_base64 = get_image_base64(img_url)

        return {
            "post_id": post_url.split('/')[-1].split('-')[0],
            "title": title,
            "url": post_url,
            "category": category,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "date": date_str,
            "download_links": full_links,
            "image_base64": image_base64
        }
    except Exception as e:
        log(f"Error scraping post {post_url}: {e}")
        return None

def save_chunk(items):
    if not items:
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"chunk_{timestamp}.json"
    filepath = os.path.join(DATA_DIR, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    log(f"Saved chunk with {len(items)} items to {filename}")

def main():
    state = load_state()
    current_page = state.get("current_page_index", 1)
    last_url = state.get("last_scraped_url")
    total_scraped = state.get("total_items_scraped", 0)
    
    log(f"Started run. Resuming from Page {current_page}")
    current_chunk = []
    
    try:
        while True:
            if current_page == 1:
                url = BASE_URL
            else:
                url = PAGE_URL_TEMPLATE.format(current_page)
                
            log(f"Processing page {current_page}: {url}")
            headers = {"User-Agent": ua.random}
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code != 200:
                log(f"Finished or Error: Page {current_page} returned {response.status_code}")
                break
                
            soup = BeautifulSoup(response.text, 'html.parser')
            post_cards = soup.select('article.post')
            if not post_cards:
                log("No more posts found. Exiting.")
                break
                
            log(f"Found {len(post_cards)} posts on page {current_page}")
            
            for card in post_cards:
                link_tag = card.select_one('.post__thumb a')
                if not link_tag: continue
                    
                post_url = link_tag.get('href')
                if not post_url.startswith('http'):
                    post_url = "https://codelist.cc" + post_url
                
                # If we are on page 1 and find the last scraped URL, we are up to date
                if post_url == last_url and current_page == 1:
                    log(f"Reached previously scraped URL: {post_url}. Run complete.")
                    return
                
                time.sleep(random.uniform(2, 5))
                post_data = scrape_post_details(post_url)
                
                if post_data:
                    current_chunk.append(post_data)
                    total_scraped += 1
                    
                    if len(current_chunk) >= CHUNK_SIZE:
                        save_chunk(current_chunk)
                        current_chunk = []
                        state["last_scraped_url"] = post_url
                        state["total_items_scraped"] = total_scraped
                        save_state(state)

            current_page += 1
            state["current_page_index"] = current_page
            save_state(state)
            time.sleep(random.uniform(3, 7))

    except KeyboardInterrupt:
        log("Run interrupted.")
    except Exception as e:
        log(f"Fatal error: {e}")
    finally:
        if current_chunk:
            save_chunk(current_chunk)
            state["last_scraped_url"] = current_chunk[-1]["url"]
            state["total_items_scraped"] = total_scraped
            save_state(state)
        log(f"Finished run. Total items scraped: {total_scraped}")

if __name__ == "__main__":
    main()
