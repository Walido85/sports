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
    
    # 1. Click all potential buttons to reveal hidden phone numbers
    try:
        buttons = page.locator("text=/Afficher|Appeler|Numéro/i, button")
        for i in range(buttons.count()):
            try:
                buttons.nth(i).click(timeout=500)
            except:
                pass
        page.wait_for_timeout(2000)
    except:
        pass

    # 2. Find any heading that contains the word "pharmacie"
    headings = page.locator("h1, h2, h3, h4, h5, strong")
    count = headings.count()
    print(f"      Found {count} potential titles on page. Parsing...")

    for i in range(count):
        try:
            heading = headings.nth(i)
            name = heading.inner_text().strip()

            # Filter out random text
            if len(name) < 5 or "pharmacie" not in name.lower():
                continue

            # Grab the text block immediately surrounding this heading
            block_text = heading.evaluate("el => { let p = el.parentElement; return p ? (p.parentElement ? p.parentElement.innerText : p.innerText) : ''; }")
            
            if not block_text:
                continue

            # Regex to find a standard 8-digit Tunisian phone number in the block
            phone_match = re.search(r'(?:\+?216)?[\s.-]*([2-9]\d)[\s.-]*(\d{3})[\s.-]*(\d{3})', block_text)
            phone = ""
            if phone_match:
                raw_phone = re.sub(r'\D', '', phone_match.group(0))
                phone = raw_phone[-8:]

            # Extract the first line that looks like an address
            address = ""
            lines = [line.strip() for line in block_text.split('\n') if line.strip()]
            for line in lines:
                if line != name and not re.search(r'\d{8}', line) and "Afficher" not in line and "Itinéraire" not in line:
                    address = line
                    break

            # Only append if we successfully linked a name and a phone number
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
        except:
            continue

    print(f"      ✅ Extracted {len(results)} pharmacies")
    return results

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Scraper - Text Block Engine")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844}
        )
        page = context.new_page()

        for city in CITIES:
            route = "tunis" if city == "grand-tunis" else city
            url = f"{BASE_URL}/pharmacie/garde/{route}"
            
            print(f"\n   🌐 {city.upper()} → {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                
                # Scroll to load dynamic content
                for _ in range(3):
                    page.mouse.wheel(0, 1500)
                    page.wait_for_timeout(1000)
                    
                pharmacies = parse_pharmacies(page, city)
                all_pharmacies.extend(pharmacies)
            except Exception as e:
                print(f"      ❌ Error on {city}: {e}")

        browser.close()

    # Deduplicate entries by phone number
    seen = set()
    unique = [p for p in all_pharmacies if p["telephone"] and not (p["telephone"] in seen or seen.add(p["telephone"]))]

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
