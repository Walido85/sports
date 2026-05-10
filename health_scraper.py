import json
import os
import csv
import time
import re
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

def parse_pharmacies(page, city):
    results = []
    # Target common list structures used by Med.tn
    cards = page.locator(".search-result, .card, .liste-praticien, [class*='list-item'], li")
    
    try:
        cards.first.wait_for(timeout=5000)
    except:
        print("      No cards visible or page format changed.")
        return results
        
    count = cards.count()
    print(f"      Found {count} potential elements")

    for i in range(count):
        card = cards.nth(i)
        try:
            full_text = card.inner_text()
            
            # Filter out irrelevant list items
            if "Pharmacie" not in full_text and "Afficher le numéro" not in full_text:
                continue

            # Extract Name
            name_loc = card.locator("h2, h3, .name, strong").first
            name = name_loc.inner_text().strip() if name_loc.count() > 0 else full_text.split('\n')[0].strip()

            # Extract Address
            address_loc = card.locator(".address, .adr, p, address").first
            address = address_loc.inner_text().strip() if address_loc.count() > 0 else ""

            # Click to reveal phone number
            phone_btn = card.locator("text='Afficher le numéro', a[href^='tel'], [class*='phone'], [class*='call']").first
            if phone_btn.count() > 0 and phone_btn.is_visible():
                try:
                    phone_btn.click(timeout=3000)
                    page.wait_for_timeout(1000) # Wait for DOM to append number
                    full_text = card.inner_text() # Refresh text
                except:
                    pass
            
            # Extract and format Phone
            phone = ""
            match = re.search(r'(\+?216)?[\s.-]*(\d{2})[\s.-]*(\d{3})[\s.-]*(\d{3,4})', full_text)
            if match:
                raw_phone = re.sub(r'\D', '', ''.join(match.groups()))
                phone = raw_phone[3:] if raw_phone.startswith("216") and len(raw_phone) > 8 else raw_phone

            if name and phone:
                results.append({
                    "nom": name,
                    "adresse": address,
                    "telephone": phone,
                    "ville": city.replace("-", " ").title(),
                    "type_garde": "Garde",
                    "source": "med.tn",
                    "scraped_at": time.strftime("%Y-%m-%d %H:%M")
                })
        except Exception:
            continue

    print(f"      ✅ Extracted {len(results)} pharmacies")
    return results

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Scraper - Mobile Optimized")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844}
        )
        page = context.new_page()

        for city in CITIES:
            # Med.tn uses 'tunis' instead of 'grand-tunis' in its route
            route = "tunis" if city == "grand-tunis" else city
            url = f"{BASE_URL}/pharmacie/garde/{route}"
            
            print(f"\n   🌐 {city.upper()} → {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                
                # Scroll down to trigger any lazy-loaded entries
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(3000)
                
                pharmacies = parse_pharmacies(page, city)
                all_pharmacies.extend(pharmacies)
            except Exception as e:
                print(f"      ❌ Error {city}: {e}")

        browser.close()

    # Deduplicate by phone number
    seen = set()
    unique = [p for p in all_pharmacies if p["telephone"] and not (p["telephone"] in seen or seen.add(p["telephone"]))]

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
