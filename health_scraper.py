import json
import os
import csv
import time
import re
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "https://www.med.tn"

# Major cities
CITIES = ["tunis", "ariana", "ben-arous", "sfax", "sousse", "nabeul", "grand-tunis"]

TYPES = ["Ouverte", "Jour", "Nuit", "Garde"]

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

def parse_pharmacies(page, city, ptype):
    results = []
    cards = page.query_selector_all(".list__, .listpharmacy .list__, article, .card, li, .searchResults-itemDoctor")
    
    print(f"      Found {len(cards)} cards for {ptype}")

    for card in cards:
        try:
            name_el = card.query_selector(".list__label--name, .practitioner-name, h2, h3, strong")
            name = name_el.inner_text().strip() if name_el else ""
            if not name or len(name) < 4:
                continue

            addr_el = card.query_selector(".list__label--adr, .practitioner-address, p")
            address = addr_el.inner_text().strip() if addr_el else ""

            phone = ""
            phone_el = card.query_selector("a[href^='tel'], .button__call")
            if phone_el:
                href = phone_el.get_attribute("href") or ""
                phone = href.replace("tel:", "").strip() if "tel:" in href else phone_el.inner_text().strip()

            # Fallback regex for phone
            if not phone:
                text = card.inner_text()
                match = re.search(r'(\+?216)?[\s.-]*(\d{2})[\s.-]*(\d{3})[\s.-]*(\d{3})', text)
                if match:
                    phone = ''.join(match.groups()).replace(" ", "")

            phone = re.sub(r'\D', '', phone)

            if name and phone:
                results.append({
                    "nom": name,
                    "adresse": address,
                    "telephone": phone,
                    "ville": city.replace("-", " ").title(),
                    "type_garde": ptype,
                    "source": "med.tn",
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M")
                })
        except:
            continue
    return results

def scrape_city_type(page, city_slug, ptype):
    # Use main garde/search page
    url = f"{BASE_URL}/pharmacie/garde/{city_slug}"
    print(f"   🌐 {city_slug.upper()} | {ptype} → {url}")
    
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(4)
        
        # Try to click the corresponding filter if possible
        try:
            filter_btn = page.query_selector(f"label:has-text('{ptype}'), input[value*='{ptype.lower()}'], [class*='{ptype.lower()}']")
            if filter_btn:
                filter_btn.click()
                time.sleep(2)
        except:
            pass

        pharmacies = parse_pharmacies(page, city_slug, ptype)
        print(f"      ✅ Extracted {len(pharmacies)} pharmacies")
        return pharmacies
    except Exception as e:
        print(f"      ❌ Error {city_slug}/{ptype}: {e}")
        return []

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Scraper - Matching App Filters (Ouverte/Jour/Nuit/Garde)...")
