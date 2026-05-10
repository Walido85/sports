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
    
    # Primary selector from your HTML audit
    cards = page.query_selector_all(".list__, .listpharmacy .list__, article, .card-doctor")
    print(f"      Found {len(cards)} cards")

    for card in cards:
        try:
            # Name
            name_el = card.query_selector(".list__label--name, .practitioner-name, h2, h3, strong")
            name = name_el.inner_text().strip() if name_el else ""
            if not name or len(name) < 5:
                continue

            # Address
            addr_el = card.query_selector(".list__label--adr, .practitioner-address, p")
            address = addr_el.inner_text().strip() if addr_el else ""

            # Phone - most reliable
            phone = ""
            phone_links = card.query_selector_all("a[href^='tel:']")
            for link in phone_links:
                href = link.get_attribute("href") or ""
                if href.startswith("tel:"):
                    phone = href.replace("tel:", "").strip()
                    break

            if not phone:
                text = card.inner_text()
                match = re.search(r'(\+?216)?[\s.-]*(\d{2})[\s.-]*(\d{3})[\s.-]*(\d{3,4})', text)
                if match:
                    phone = re.sub(r'\D', '', ''.join(match.groups()))

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

    print(f"      ✅ Extracted {len(results)} pharmacies from {city}")
    return results

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Scraper - Full Audit Version (Senior Dev)")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 900},
            locale="fr-TN"
        )
        page = context.new_page()

        for city in CITIES:
            url = f"{BASE_URL}/pharmacie/garde/{city}" if city != "grand-tunis" else f"{BASE_URL}/pharmacie/grand-tunis"
            print(f"\n   🌐 Scraping {city.upper()} → {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=20000)
                time.sleep(5)  # Critical wait for JS cards
                
                pharmacies = parse_pharmacies(page, city)
                all_pharmacies.extend(pharmacies)
            except Exception as e:
                print(f"      ❌ Error on {city}: {e}")
            time.sleep(2)

        browser.close()

    # Deduplicate by phone
    seen = set()
    unique = [p for p in all_pharmacies if p["telephone"] and p["telephone"] not in seen and not seen.add(p["telephone"])]

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique pharmacies: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
