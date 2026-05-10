import json
import os
import csv
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "https://www.med.tn"
CITIES = ["tunis", "ariana", "ben-arous", "sfax", "sousse", "nabeul", "grand-tunis"]

def save_json(name, data):
    path = os.path.join(OUTPUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 {name} — {len(data)} pharmacies")

def save_csv(name, rows):
    if not rows: return
    path = os.path.join(OUTPUT_DIR, name)
    cols = ["nom", "adresse", "telephone", "ville", "type_garde", "source", "scraped_at"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)
    print(f"📄 {name} — {len(rows)} rows")

def parse_pharmacies(page, city):
    results = []
    
    # Main selectors from audited HTML
    cards = page.query_selector_all(".listpharmacy .list__, .list__, article, .card-doctor, li")
    print(f"      Found {len(cards)} potential cards")

    for card in cards:
        try:
            name_el = card.query_selector(".list__label--name, h2, h3, strong, .practitioner-name")
            name = name_el.inner_text().strip() if name_el else ""

            if not name or "pharmacie" not in name.lower() and len(name) < 5:
                continue

            addr_el = card.query_selector(".list__label--adr, .practitioner-address, [class*='adr']")
            address = addr_el.inner_text().strip() if addr_el else ""

            phone_el = card.query_selector("a[href^='tel:'], .button__call, [class*='tel'], [class*='phone']")
            phone = ""
            if phone_el:
                href = phone_el.get_attribute("href") or ""
                if "tel:" in href:
                    phone = href.replace("tel:", "").strip()
                else:
                    phone = phone_el.inner_text().strip()

            # Clean phone
            phone = re.sub(r'\D', '', phone)

            if name and (phone or address):
                results.append({
                    "nom": name,
                    "adresse": address,
                    "telephone": phone,
                    "ville": city.capitalize(),
                    "type_garde": "Garde",
                    "source": "med.tn",
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M")
                })
        except Exception:
            continue
    
    return results

def scrape_city(page, city_slug):
    url = f"{BASE_URL}/pharmacie/garde/{city_slug}" if city_slug != "grand-tunis" else f"{BASE_URL}/pharmacie/grand-tunis"
    print(f"   🌐 Scraping {city_slug.upper()} → {url}")
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_load_state("networkidle", timeout=12000)
        time.sleep(3)  # Critical for dynamic load
        
        pharmacies = parse_pharmacies(page, city_slug)
        print(f"      ✅ Extracted {len(pharmacies)} pharmacies")
        return pharmacies
    except Exception as e:
        print(f"      ❌ Error {city_slug}: {e}")
        return []

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Pharmacy Scraper - Starting (Audited Version)...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1366, "height": 900}
        )
        page = context.new_page()

        for city in CITIES:
            results = scrape_city(page, city)
            all_pharmacies.extend(results)
            time.sleep(1.5)

        browser.close()

    # Dedup by phone
    seen = set()
    unique = [p for p in all_pharmacies if p["telephone"] and p["telephone"] not in seen and not seen.add(p["telephone"])]

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
