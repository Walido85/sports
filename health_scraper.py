import json
import os
import csv
import time
import re
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "https://www.med.tn"
CITIES = ["tunis", "ariana", "ben-arous", "sfax", "sousse", "grand-tunis"]

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
    # Very broad selector
    cards = page.query_selector_all("body *")
    print(f"      Page length: {len(page.content())} chars | Looking for pharmacies...")

    # Extract using text + regex (most reliable when JS is blocked)
    text = page.inner_text("body")
    lines = [line.strip() for line in text.split('\n') if line.strip()]

    current_name = ""
    for line in lines:
        if any(k in line.lower() for k in ["pharmacie", "pharma"]):
            current_name = line
            continue
        
        # Phone detection
        if re.search(r'\d{2,3}[\s.-]+\d{2,3}', line):
            phone_match = re.search(r'(\+?216)?[\s.-]*(\d{2})[\s.-]*(\d{3})[\s.-]*(\d{3,4})', line)
            if phone_match:
                phone = ''.join(phone_match.groups()).replace(" ", "").replace(".", "").replace("-", "")
                if len(phone) >= 8:
                    results.append({
                        "nom": current_name or "Pharmacie de Garde",
                        "adresse": "",
                        "telephone": phone,
                        "ville": city.replace("-", " ").title(),
                        "type_garde": "Garde",
                        "source": "med.tn",
                        "scraped_at": time.strftime("%Y-%m-%d %H:%M")
                    })
                    current_name = ""

    print(f"      ✅ Extracted {len(results)} via text parsing")
    return results

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Scraper with Stealth Mode...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-gpu"
            ]
        )
        
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 900},
            locale="fr-TN"
        )
        
        # Stealth
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
        """)
        
        page = context.new_page()

        for city in CITIES:
            url = f"{BASE_URL}/pharmacie/garde/{city}"
            print(f"   🌐 Trying {city} → {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=20000)
                time.sleep(5)  # Give time to bypass protection
                
                pharmacies = parse_pharmacies(page, city)
                all_pharmacies.extend(pharmacies)
            except Exception as e:
                print(f"      ❌ Error {city}: {e}")
            time.sleep(2)

        browser.close()

    # Dedup
    seen = set()
    unique = [p for p in all_pharmacies if p["telephone"] and p["telephone"] not in seen and not seen.add(p["telephone"])]

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
