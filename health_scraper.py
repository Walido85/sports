import json
import os
import csv
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── CONFIG ────────────────────────────────────────────────────────────────────
OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "https://www.med.tn"
GARDE_BASE = "https://www.med.tn/pharmacie/garde"

# Limit for CI (you can expand later)
CITIES = ["Tunis", "Ariana", "Ben Arous", "Sfax", "Sousse"]  # Start small

TYPES = ["Garde"]  # Simplified - site mostly shows current garde

def save_json(name, data):
    path = os.path.join(OUTPUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved {name} — {len(data) if isinstance(data, list) else 1} records")

def save_csv(name, rows, columns):
    if not rows:
        return
    path = os.path.join(OUTPUT_DIR, name)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    print(f"📄 Saved {name} — {len(rows)} rows")

# ── PARSER ────────────────────────────────────────────────────────────────────
def parse_pharmacies(page):
    results = []
    # Strong selectors based on site structure
    cards = page.query_selector_all("article, .pharmacy, .card, [class*='pharmacie'], li")
    
    print(f"      Found {len(cards)} potential cards")
    
    for card in cards[:50]:  # safety limit
        try:
            text = card.inner_text().strip()
            if len(text) < 15:
                continue

            name = card.query_selector("h2, h3, strong, [class*='name'], [class*='title']")
            name = name.inner_text().strip() if name else ""

            if not name:
                continue

            phone = ""
            phone_el = card.query_selector("a[href^='tel'], [class*='tel'], [class*='phone']")
            if phone_el:
                href = phone_el.get_attribute("href") or ""
                phone = re.sub(r'\D', '', href.replace("tel:", "")) or phone_el.inner_text().strip()

            address = ""
            addr_el = card.query_selector("p, [class*='adresse'], [class*='address'], span")
            if addr_el:
                address = addr_el.inner_text().strip()

            results.append({
                "nom": name,
                "adresse": address,
                "telephone": phone,
                "ville": "",  # filled later
                "type_garde": "Garde",
                "source": "med.tn",
                "scraped_at": time.strftime("%Y-%m-%d %H:%M")
            })
        except:
            continue
    return results

def scrape_city(page, city):
    url = f"{GARDE_BASE}/{city.lower()}"
    print(f"   🌐 Scraping {city} → {url}")
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_load_state("networkidle", timeout=10000)
        time.sleep(2)  # let dynamic content load
        
        pharmacies = parse_pharmacies(page)
        
        for p in pharmacies:
            p["ville"] = city
            p["gouvernorat"] = city
            
        print(f"      ✅ {len(pharmacies)} pharmacies found for {city}")
        return pharmacies
    except Exception as e:
        print(f"      ❌ Error {city}: {e}")
        return []

# ── MAIN ──────────────────────────────────────────────────────────────────────
def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 Starting med.tn Pharmacy Scraper (CI optimized)...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()

        for city in CITIES:
            results = scrape_city(page, city)
            all_pharmacies.extend(results)
            time.sleep(1.5)  # be gentle

        browser.close()

    # Deduplicate
    seen = set()
    unique = []
    for p in all_pharmacies:
        key = (p["nom"].lower(), p["telephone"])
        if key not in seen and p["nom"]:
            seen.add(key)
            unique.append(p)

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique pharmacies: {len(unique)}")

    COLUMNS = ["nom", "adresse", "telephone", "ville", "gouvernorat", "type_garde", "source", "scraped_at"]
    
    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique, COLUMNS)

if __name__ == "__main__":
    main()
