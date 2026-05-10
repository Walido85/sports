import json
import os
import csv
import time
import re
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "https://www.med.tn"

# All 24 Tunisian Governorates + Grand Tunis + Djerba
CITIES = [
    "grand-tunis", "tunis", "ariana", "ben-arous", "manouba", 
    "bizerte", "nabeul", "zaghouan", "beja", "jendouba", "le-kef", "siliana",
    "sousse", "monastir", "mahdia", "kairouan", "kasserine", "sidi-bouzid",
    "sfax", "gabes", "medenine", "tataouine", "gafsa", "tozeur", "kebili", "djerba"
]

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
    
    blocks = soup.find_all('div', class_='card-doctor-block')

    for block in blocks:
        try:
            # 1. Extract Name & Determine Type (Jour/Nuit)
            name_el = block.find('div', class_='list__label--name')
            original_name = name_el.get_text(strip=True) if name_el else ""
            
            garde_type = "Garde"
            if "nuit" in original_name.lower():
                garde_type = "Nuit"
            elif "jour" in original_name.lower():
                garde_type = "Jour"

            # Clean the name (Removes "Pharmacie de garde/nuit/jour")
            clean_name = re.sub(r'(?i)^pharmacie\s*(de\s*garde|du\s*jour|de\s*nuit|de\s*jour)?\s*(-|:)?\s*', '', original_name).strip()

            # 2. Extract Address
            address = ""
            addr_elems = block.find_all('div', class_='list__label--adr')
            for addr in addr_elems:
                if addr.find('i', class_='pfadmicon-glyph-686'):
                    address = addr.get_text(strip=True).replace("Tunisie", "").strip()
                    break

            # 3. Extract Phone (Directly from HTML, avoiding clicks)
            phones = []
            modal = block.find('div', class_='phonemodal')
            if modal:
                call_tags = modal.find_all('a', class_='calltel')
                for tag in call_tags:
                    raw_phone = tag.get_text(strip=True)
                    clean_phone = ''.join(filter(str.isdigit, raw_phone))
                    
                    if clean_phone.startswith("216") and len(clean_phone) > 8:
                        clean_phone = clean_phone[3:]
                        
                    if clean_phone and len(clean_phone) >= 8:
                        # Adding +216 forces Excel to treat it as Text, stopping the 7.1E+07 bug
                        formatted_phone = f"+216 {clean_phone[-8:-6]} {clean_phone[-6:-3]} {clean_phone[-3:]}"
                        phones.append(formatted_phone)
            
            phone_str = " | ".join(phones)

            if clean_name and phone_str:
                results.append({
                    "nom": clean_name,
                    "adresse": address,
                    "telephone": phone_str,
                    "ville": city.replace("-", " ").title(),
                    "type_garde": garde_type,
                    "source": "med.tn",
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M")
                })
        except Exception:
            continue

    print(f"      ✅ Extracted {len(results)} pharmacies on this page")
    return results

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Scraper - Pagination & Full Data Engine")

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
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                
                # PAGINATION LOOP
                page_num = 1
                while True:
                    # Wait for cards to load
                    try:
                        page.wait_for_selector(".card-doctor-block", timeout=10000)
                    except:
                        break # Stop if no cards load (end of results)
                        
                    html_content = page.content()
                    pharmacies = parse_html_with_bs4(html_content, city)
                    
                    if not pharmacies:
                        break # Stop loop if extraction fails completely
                        
                    all_pharmacies.extend(pharmacies)
                    
                    # Check for "Suivant »" button
                    next_btn = page.locator("a:has-text('Suivant')")
                    if next_btn.count() > 0 and next_btn.is_visible():
                        print(f"      ➡️ Clicking 'Suivant' to load page {page_num + 1}...")
                        next_btn.first.click()
                        page.wait_for_timeout(3500) # Wait for the new results to load
                        page_num += 1
                    else:
                        break # No "Suivant" button found, move to next city
                        
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
    print(f"\n✅ Finished in {elapsed}s | Total unique pharmacies: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
