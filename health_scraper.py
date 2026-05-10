import json
import os
import csv
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "https://www.med.tn"
CITIES = ["grand-tunis", "tunis", "ariana", "ben-arous", "sfax", "sousse"]

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

def parse_html_with_bs4(html_content, city):
    results = []
    soup = BeautifulSoup(html_content, "html.parser")
    
    # Based on your HTML, every pharmacy is wrapped in this class
    blocks = soup.find_all('div', class_='card-doctor-block')
    print(f"      Found {len(blocks)} pharmacy blocks in HTML.")

    for block in blocks:
        try:
            # 1. Extract Name
            name_el = block.find('div', class_='list__label--name')
            name = name_el.get_text(strip=True) if name_el else ""
            
            # Clean "Pharmacie de garde" from the name if present
            if "pharmacie de garde" in name.lower():
                name = name[18:].strip()
            elif "pharmacie" in name.lower():
                name = name[9:].strip()

            # 2. Extract Address (Targeting the div with the specific location icon)
            address = ""
            addr_elems = block.find_all('div', class_='list__label--adr')
            for addr in addr_elems:
                if addr.find('i', class_='pfadmicon-glyph-686'):
                    # Get text and remove "Tunisie" from the end
                    address = addr.get_text(strip=True).replace("Tunisie", "").strip()
                    break

            # 3. Extract Phone (Directly from the hidden phonemodal!)
            phones = []
            modal = block.find('div', class_='phonemodal')
            if modal:
                call_tags = modal.find_all('a', class_='calltel')
                for tag in call_tags:
                    raw_phone = tag.get_text(strip=True)
                    # Clean the number (e.g., +216.73.374.630 -> 73374630)
                    clean_phone = ''.join(filter(str.isdigit, raw_phone))
                    if clean_phone.startswith("216") and len(clean_phone) > 8:
                        clean_phone = clean_phone[3:]
                    if clean_phone:
                        phones.append(clean_phone)
            
            # If they have multiple numbers, join them with a dash
            phone_str = " - ".join(phones)

            if name and phone_str:
                results.append({
                    "nom": name,
                    "adresse": address,
                    "telephone": phone_str,
                    "ville": city.replace("-", " ").title(),
                    "type_garde": "Garde",
                    "source": "med.tn",
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M")
                })
        except Exception as e:
            continue

    print(f"      ✅ Extracted {len(results)} pharmacies")
    return results

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Scraper - Instant HTML Parsing Engine")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for city in CITIES:
            route = "tunis" if city == "grand-tunis" else city
            url = f"{BASE_URL}/pharmacie/garde/{route}"
            
            print(f"\n   🌐 {city.upper()} → {url}")
            try:
                # Load the page and immediately grab the HTML. No clicking. No waiting.
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                html_content = page.content()
                
                # Parse the raw HTML using BeautifulSoup
                pharmacies = parse_html_with_bs4(html_content, city)
                all_pharmacies.extend(pharmacies)
            except Exception as e:
                print(f"      ❌ Error on {city}: {e}")

        browser.close()

    # Deduplicate entries by phone number
    seen = set()
    unique = []
    for p in all_pharmacies:
        if p["telephone"] and p["telephone"] not in seen:
            seen.add(p["telephone"])
            unique.append(p)

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
