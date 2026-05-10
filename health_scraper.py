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
GARDE_URL = "https://www.med.tn/pharmacie/garde"

CITIES = [
    "Tunis", "Ariana", "Ben Arous", "Manouba", "Nabeul", "Zaghouan",
    "Bizerte", "Beja", "Jendouba", "Le Kef", "Siliana", "Sousse",
    "Monastir", "Mahdia", "Sfax", "Kairouan", "Kasserine", "Sidi Bouzid",
    "Gabes", "Medenine", "Tataouine", "Gafsa", "Tozeur", "Kebili",
]

TYPES = ["Day", "Night", "Duty", "Opened"]  # Map to site terms if needed

# ── SAVE ──────────────────────────────────────────────────────────────────────
def save_json(name, data):
    path = os.path.join(OUTPUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    count = len(data) if isinstance(data, list) else 1
    print(f"💾 {name} — {count} records")

def save_csv(name, rows, columns):
    if not rows:
        return
    path = os.path.join(OUTPUT_DIR, name)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"📄 {name} — {len(rows)} rows")

# ── PARSE ─────────────────────────────────────────────────────────────────────
def parse_pharmacy_cards(page):
    results = []
    cards = page.query_selector_all(
        "article, .pharmacy-card, .pharmacy-item, [class*='pharmacy'], "
        ".result-item, .card, [data-testid*='pharmacy']"
    )
    for card in cards:
        try:
            text = card.inner_text().strip()
            if not text or len(text) < 10:
                continue

            # Name
            name_el = card.query_selector("h2, h3, h4, [class*='name'], [class*='title']")
            name = name_el.inner_text().strip() if name_el else ""

            # Address / Delegation
            addr_el = card.query_selector("[class*='address'], [class*='adresse'], p, [class*='location']")
            address = addr_el.inner_text().strip() if addr_el else ""

            # Phone
            phone_el = card.query_selector("a[href^='tel:'], [class*='phone'], [class*='tel']")
            phone = ""
            if phone_el:
                href = phone_el.get_attribute("href") or ""
                phone = re.sub(r'[^\d+]', '', href.replace("tel:", "").strip() or phone_el.inner_text().strip())

            # Status
            status_el = card.query_selector("[class*='status'], [class*='badge'], [class*='garde'], [class*='open']")
            status = status_el.inner_text().strip() if status_el else ""

            # GPS
            map_el = card.query_selector("a[href*='maps.google'], a[href*='lat'], a[href*='gps']")
            lat, lng = "", ""
            if map_el:
                href = map_el.get_attribute("href") or ""
                coords = re.search(r"[-+]?\d*\.\d+[,/&][-+]?\d*\.\d+", href)
                if coords:
                    parts = re.findall(r"[-+]?\d*\.\d+", coords.group(0))
                    if len(parts) >= 2:
                        lat, lng = parts[0], parts[1]

            # Hours / other
            hours_el = card.query_selector("[class*='hour'], [class*='horaire'], [class*='schedule']")
            hours = hours_el.inner_text().strip() if hours_el else ""

            if name:
                results.append({
                    "nom": name,
                    "adresse": address,
                    "telephone": phone,
                    "ville": "",  # filled later
                    "delegation": "",
                    "horaires": hours,
                    "statut": status,
                    "latitude": lat,
                    "longitude": lng,
                })
        except Exception:
            continue
    return results

def scrape_city(page, city, ptype):
    try:
        url = f"{GARDE_URL}/{city.lower() if city else ''}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)

        # Filter by type if possible (adjust selector per site)
        # Example: click on tabs if exist
        time.sleep(2)

        all_results = []
        page_num = 1
        while True:
            results = parse_pharmacy_cards(page)
            new_results = [r for r in results if r not in all_results]
            if not new_results and page_num > 1:
                break
            all_results.extend(new_results)
            print(f"      Page {page_num} ({city}/{ptype}): {len(new_results)} new")

            # Pagination / Scroll
            try:
                next_btn = page.query_selector("button[aria-label*='next'], a.next, [class*='next'], button:has-text('Suivant')")
                if next_btn and next_btn.is_visible():
                    next_btn.click()
                    page.wait_for_load_state("networkidle", timeout=10000)
                    page_num += 1
                    continue
            except Exception:
                pass

            # Infinite scroll fallback
            prev_h = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(2)
            new_h = page.evaluate("document.body.scrollHeight")
            if new_h == prev_h:
                break
            page_num += 1

        for r in all_results:
            r["ville"] = city
            r["type_garde"] = ptype
            r["gouvernorat"] = city
            r["source"] = "med.tn"
        return all_results
    except Exception as e:
        print(f"      ❌ Error {city}/{ptype}: {e}")
        return []

def scrape_medtn():
    print("\n📡 med.tn — scraping pharmacies...")
    all_pharmacies = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1366, "height": 768},
            locale="fr-TN"
        )
        page = context.new_page()

        for city in CITIES:
            print(f"\n   📍 {city}")
            for ptype in TYPES:
                print(f"      → {ptype}")
                results = scrape_city(page, city, ptype)
                all_pharmacies.extend(results)
                time.sleep(1)

        browser.close()
    return all_pharmacies

def dedup(records):
    seen = set()
    unique = []
    for r in records:
        key = (r.get("nom", "").lower(), r.get("telephone", "").replace(" ", ""))
        if key not in seen and key[0]:
            seen.add(key)
            unique.append(r)
    return unique

def normalize(records):
    for r in records:
        r["telephone"] = re.sub(r'[^\d+]', '', r.get("telephone", ""))
    return records

def main():
    start = time.time()
    raw = scrape_medtn()
    pharmacies = dedup(normalize(raw))

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Done in {elapsed}s | Total unique: {len(pharmacies)}")

    COLUMNS = ["nom", "adresse", "telephone", "ville", "delegation", "horaires",
               "statut", "latitude", "longitude", "type_garde", "gouvernorat", "source"]

    save_json("pharmacies_all.json", pharmacies)
    save_csv("pharmacies_all.csv", pharmacies, COLUMNS)
    print("\n📁 Files saved in ./output/")

if __name__ == "__main__":
    main()
