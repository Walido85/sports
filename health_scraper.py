import json
import os
import csv
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── CONFIG ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

GARDE_BASE = "https://www.med.tn/pharmacie/garde"

# Start with major cities for CI speed - expand later
CITIES = ["tunis", "ariana", "ben-arous", "sfax", "sousse", "nabeul"]

def save_json(name, data):
    path = os.path.join(OUTPUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved {name} — {len(data)} pharmacies")

def save_csv(name, rows):
    if not rows:
        return
    path = os.path.join(OUTPUT_DIR, name)
    columns = ["nom", "adresse", "telephone", "ville", "type_garde", "source"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"📄 Saved {name} — {len(rows)} rows")

# ── EXTRACT PHARMACIES ───────────────────────────────────────────────────────
def parse_page(page, city):
    results = []
    
    # Wait for content
    try:
        page.wait_for_selector("body", timeout=10000)
        time.sleep(3)  # Allow JS to render list
    except:
        pass

    # Get all text and extract structured data (most reliable for this site)
    body_text = page.inner_text("body")
    
    # Find pharmacy blocks by phone patterns
    phone_pattern = r'(\+?216)?[\s.-]*(\d{2,3})[\s.-]*(\d{2,3})[\s.-]*(\d{2,3})[\s.-]*(\d{2,3})'
    phones = re.findall(phone_pattern, body_text)
    
    lines = body_text.split('\n')
    current_name = ""
    current_address = ""
    
    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue
            
        # Look for pharmacy name (usually before phone)
        if any(word in line.lower() for word in ["pharmacie", "pharma", "garde"]):
            current_name = line
            continue
            
        # Phone found
        if re.search(r'\d{2,3}[\s.-]+\d{2,3}', line):
            phone_match = re.search(r'(\+?216)?[\s.-]*(\d{2}[\s.-]*){3,4}\d{2,3}', line)
            phone = phone_match.group(0).replace(" ", "").replace("-", "").replace(".", "") if phone_match else ""
            
            if phone and len(phone) >= 8:
                results.append({
                    "nom": current_name or "Pharmacie de Garde",
                    "adresse": current_address,
                    "telephone": phone,
                    "ville": city.capitalize(),
                    "type_garde": "Garde",
                    "source": "med.tn",
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M")
                })
                current_name = ""
                current_address = ""
    
    # Fallback: extract all cards if any
    cards = page.query_selector_all("article, li, div[class*='pharma'], p")
    print(f"      Found {len(cards)} elements | Extracted {len(results)} via text")
    
    return results

def scrape_city(page, city_slug):
    url = f"{GARDE_BASE}/{city_slug}"
    print(f"   🌐 {city_slug.upper()} → {url}")
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_load_state("networkidle", timeout=15000)
        
        pharmacies = parse_page(page, city_slug)
        print(f"      ✅ {len(pharmacies)} pharmacies for {city_slug}")
        return pharmacies
    except Exception as e:
        print(f"      ❌ Error {city_slug}: {e}")
        return []

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Garde Scraper - Starting...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1366, "height": 768}
        )
        page = context.new_page()

        for city in CITIES:
            results = scrape_city(page, city)
            all_pharmacies.extend(results)
            time.sleep(2)

        browser.close()

    # Deduplicate
    seen = set()
    unique = []
    for p in all_pharmacies:
        key = p["telephone"]
        if key and key not in seen:
            seen.add(key)
            unique.append(p)

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
