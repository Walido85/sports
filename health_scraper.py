"""
TuniWave Health Scraper — med.tn
Scrapes all pharmacies in Tunisia with Day / Night / Duty / Opened status
Uses Playwright to handle JavaScript rendering
Run: python health_scraper.py
"""

import json
import os
import csv
import time
import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ── CONFIG ────────────────────────────────────────────────────────────────────

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

BASE_URL = "https://www.med.tn/en"

CITIES = [
    "Tunis", "Ariana", "Ben Arous", "Manouba", "Nabeul", "Zaghouan",
    "Bizerte", "Beja", "Jendouba", "Le Kef", "Siliana", "Sousse",
    "Monastir", "Mahdia", "Sfax", "Kairouan", "Kasserine", "Sidi Bouzid",
    "Gabes", "Medenine", "Tataouine", "Gafsa", "Tozeur", "Kebili",
]

TYPES = ["Day", "Night", "Duty", "Opened"]

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
    """Extract all pharmacy cards from current page state."""
    results = []

    # Wait for results to load
    try:
        page.wait_for_selector(
            "[class*='pharmacy'], [class*='Pharmacy'], [class*='card'], .result-item, article",
            timeout=8000
        )
    except PlaywrightTimeout:
        pass

    # Try to intercept JSON from network (most reliable)
    # Done via route interception in the main scraper

    # Parse HTML cards
    cards = page.query_selector_all(
        "[class*='pharmacy-card'], [class*='PharmacyCard'], "
        "[class*='pharmacy-item'], [class*='PharmacyItem'], "
        "[class*='result-card'], [class*='card-pharmacy'], "
        "article, .pharmacy, [data-testid*='pharmacy']"
    )

    for card in cards:
        try:
            text = card.inner_text()
            if not text.strip():
                continue

            # Name — usually first heading
            name_el = card.query_selector("h2, h3, h4, [class*='name'], [class*='Name'], [class*='title']")
            name = name_el.inner_text().strip() if name_el else ""

            # Address
            addr_el = card.query_selector("[class*='address'], [class*='Address'], [class*='adresse'], p")
            address = addr_el.inner_text().strip() if addr_el else ""

            # Phone
            phone_el = card.query_selector("a[href^='tel:'], [class*='phone'], [class*='Phone'], [class*='tel']")
            phone = ""
            if phone_el:
                href = phone_el.get_attribute("href") or ""
                phone = href.replace("tel:", "").strip() or phone_el.inner_text().strip()

            # Status badge
            status_el = card.query_selector("[class*='status'], [class*='badge'], [class*='garde'], [class*='open']")
            status = status_el.inner_text().strip() if status_el else ""

            # GPS coordinates from any map link
            map_el = card.query_selector("a[href*='maps'], a[href*='gps'], a[href*='lat']")
            lat, lng = "", ""
            if map_el:
                href = map_el.get_attribute("href") or ""
                coords = re.search(r"(\-?\d+\.\d+)[,&](\-?\d+\.\d+)", href)
                if coords:
                    lat, lng = coords.group(1), coords.group(2)

            # City from card if available
            city_el = card.query_selector("[class*='city'], [class*='City'], [class*='ville']")
            city = city_el.inner_text().strip() if city_el else ""

            # Working hours
            hours_el = card.query_selector("[class*='hour'], [class*='Hour'], [class*='horaire'], [class*='schedule']")
            hours = hours_el.inner_text().strip() if hours_el else ""

            if name or phone:
                results.append({
                    "nom": name,
                    "adresse": address,
                    "telephone": phone.replace(" ", ""),
                    "ville": city,
                    "horaires": hours,
                    "statut": status,
                    "latitude": lat,
                    "longitude": lng,
                })
        except Exception:
            continue

    return results


def get_all_pages(page, city, pharmacy_type):
    """Scroll / paginate through all results for a city+type combination."""
    all_results = []
    page_num = 1

    while True:
        results = parse_pharmacy_cards(page)

        if not results and page_num == 1:
            # Try raw text extraction as last resort
            body = page.inner_text()
            phones = re.findall(r"\b\d{8}\b|\b\+216\s?\d{8}\b", body)
            if phones:
                print(f"      ⚠️  Found {len(phones)} phones via text, no structured cards")
            break

        new_results = [r for r in results if r not in all_results]
        if not new_results:
            break

        all_results.extend(new_results)
        print(f"      Page {page_num}: {len(new_results)} pharmacies")

        # Try next page button
        next_btn = page.query_selector(
            "button[aria-label*='next'], a[aria-label*='next'], "
            "[class*='next-page'], [class*='NextPage'], "
            "button:has-text('Next'), a:has-text('Next'), "
            "[class*='pagination'] a:last-child, [class*='Pagination'] button:last-child"
        )

        if next_btn:
            try:
                next_btn.click()
                page.wait_for_load_state("networkidle", timeout=8000)
                page_num += 1
            except Exception:
                break
        else:
            # Try infinite scroll
            prev_height = page.evaluate("document.body.scrollHeight")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.5)
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break  # No more content
            page_num += 1

    return all_results


def search_city_type(page, city, pharmacy_type, intercepted):
    """Perform a search for a specific city and pharmacy type."""
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_load_state("networkidle", timeout=10000)
    except PlaywrightTimeout:
        pass

    try:
        # Click Pharmacy tab if needed
        pharmacy_tab = page.query_selector(
            "[class*='pharmacy-tab'], [data-tab='pharmacy'], "
            "button:has-text('Pharmacy'), a:has-text('Pharmacy')"
        )
        if pharmacy_tab:
            pharmacy_tab.click()
            time.sleep(0.5)

        # Fill city field
        city_input = page.query_selector(
            "input[placeholder*='City'], input[placeholder*='city'], "
            "input[name*='city'], select[name*='city'], "
            "[class*='city-input'], [class*='CityInput']"
        )
        if city_input:
            tag = city_input.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                city_input.select_option(label=city)
            else:
                city_input.click()
                city_input.fill(city)
                time.sleep(0.5)
                # Click dropdown option if appears
                option = page.query_selector(f"[class*='option']:has-text('{city}'), li:has-text('{city}')")
                if option:
                    option.click()

        # Select type radio: Day / Night / Duty / Opened
        type_radio = page.query_selector(
            f"input[type='radio'][value*='{pharmacy_type.lower()}'], "
            f"label:has-text('{pharmacy_type}'), "
            f"[class*='radio']:has-text('{pharmacy_type}')"
        )
        if type_radio:
            type_radio.click()
            time.sleep(0.3)

        # Click Search button
        search_btn = page.query_selector(
            "button:has-text('SEARCH'), button:has-text('Search'), "
            "button[type='submit'], [class*='search-btn'], [class*='SearchBtn']"
        )
        if search_btn:
            search_btn.click()
            page.wait_for_load_state("networkidle", timeout=12000)

        return get_all_pages(page, city, pharmacy_type)

    except Exception as e:
        print(f"      ❌ Error: {e}")
        return []


def scrape_medtn():
    print("\n📡 med.tn — scraping pharmacies (Day/Night/Duty/Opened)...")
    print(f"   Cities: {len(CITIES)} | Types: {TYPES}")

    all_pharmacies = []
    intercepted_data = []  # Will capture API responses

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="fr-FR",
        )

        # Intercept API calls — most modern sites call a JSON API
        def handle_response(response):
            url = response.url
            if any(kw in url for kw in ["pharmacy", "pharmacie", "search", "api"]):
                try:
                    ct = response.headers.get("content-type", "")
                    if "json" in ct:
                        data = response.json()
                        if isinstance(data, (list, dict)) and data:
                            intercepted_data.append({"url": url, "data": data})
                            print(f"      📦 API intercepted: {url}")
                except Exception:
                    pass

        page = context.new_page()
        page.on("response", handle_response)

        # First: detect API pattern from home page
        print("   Detecting API pattern...")
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=8000)

            # Do one test search to capture API endpoint
            search_city_type(page, "Tunis", "Night", intercepted_data)
            time.sleep(2)
        except Exception as e:
            print(f"   ⚠️  Initial probe: {e}")

        # If we captured API calls, use them directly — much faster
        if intercepted_data:
            print(f"\n   ✅ API detected! Using direct API calls for all cities/types")
            api_url = intercepted_data[0]["url"]
            print(f"   API: {api_url}")

            # Extract the API pattern and iterate all combinations
            import requests as req
            import urllib3
            urllib3.disable_warnings()

            session = req.Session()
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "Referer": BASE_URL,
            })

            # Get cookies from Playwright context
            cookies = context.cookies()
            for c in cookies:
                session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

            for city in CITIES:
                for ptype in TYPES:
                    try:
                        # Build API URL based on intercepted pattern
                        # Replace city/type params in captured URL
                        test_url = re.sub(
                            r"(city|ville|q)=[^&]*", f"\\1={city}", api_url, flags=re.IGNORECASE
                        )
                        test_url = re.sub(
                            r"(type|garde|status)=[^&]*", f"\\1={ptype.lower()}", test_url, flags=re.IGNORECASE
                        )

                        r = session.get(test_url, timeout=15, verify=False)
                        data = r.json()

                        items = data if isinstance(data, list) else \
                                data.get("data", data.get("results", data.get("pharmacies", [])))

                        if items:
                            print(f"   ✅ API {city}/{ptype}: {len(items)} pharmacies")
                            for item in items:
                                all_pharmacies.append(normalize(item, city, ptype))
                        time.sleep(0.3)
                    except Exception as e:
                        print(f"   ⚠️  API {city}/{ptype}: {e}")

        else:
            # No API captured — use full Playwright scraping per city/type
            print("\n   No API detected. Scraping via browser per city/type...")
            for city in CITIES:
                print(f"\n   📍 {city}")
                for ptype in TYPES:
                    print(f"      → {ptype}")
                    results = search_city_type(page, city, ptype, intercepted_data)
                    if results:
                        print(f"      ✅ {len(results)} pharmacies")
                        for r in results:
                            r["type_garde"] = ptype
                            r["gouvernorat"] = city
                        all_pharmacies.extend(results)
                    time.sleep(0.5)

        browser.close()

    # Save intercepted raw API data for debugging
    if intercepted_data:
        save_json("medtn_api_raw.json", intercepted_data)

    return all_pharmacies


def normalize(raw, city, ptype):
    """Normalize a raw pharmacy record from any source."""
    if isinstance(raw, dict):
        r = {k.lower(): v for k, v in raw.items()}
    else:
        return {"nom": str(raw), "ville": city, "type_garde": ptype, "source": "med.tn"}

    phone = str(r.get("phone", r.get("telephone", r.get("tel", r.get("mobile", ""))))).replace(" ", "")

    return {
        "nom":        r.get("name", r.get("nom", r.get("title", ""))),
        "adresse":    r.get("address", r.get("adresse", r.get("location", ""))),
        "telephone":  phone,
        "ville":      r.get("city", r.get("ville", r.get("governorate", city))),
        "delegation": r.get("delegation", r.get("district", "")),
        "horaires":   r.get("hours", r.get("horaires", r.get("schedule", ""))),
        "statut":     r.get("status", r.get("statut", ptype)),
        "latitude":   str(r.get("lat", r.get("latitude", ""))),
        "longitude":  str(r.get("lng", r.get("longitude", r.get("long", "")))),
        "type_garde": ptype,
        "gouvernorat": city,
        "source":     "med.tn",
    }


def dedup(records):
    seen_phone = set()
    seen_name  = set()
    unique = []
    for r in records:
        phone = r.get("telephone", "").replace(" ", "").replace(".", "")
        name  = f"{r.get('nom','')}|{r.get('ville','')}".lower()
        if phone and len(phone) >= 8:
            if phone in seen_phone:
                continue
            seen_phone.add(phone)
        else:
            if name in seen_name:
                continue
            seen_name.add(name)
        unique.append(r)
    return unique


def main():
    print("╔══════════════════════════════════════════╗")
    print("║   TuniWave Health Scraper — med.tn       ║")
    print("║   Day / Night / Duty / Opened            ║")
    print("╚══════════════════════════════════════════╝")

    start = time.time()

    raw = scrape_medtn()
    pharmacies = dedup(raw)

    day   = [p for p in pharmacies if p.get("type_garde") == "Day"]
    night = [p for p in pharmacies if p.get("type_garde") == "Night"]
    duty  = [p for p in pharmacies if p.get("type_garde") == "Duty"]

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Done in {elapsed}s")
    print(f"   Total unique:  {len(pharmacies)}")
    print(f"   Day:           {len(day)}")
    print(f"   Night:         {len(night)}")
    print(f"   Duty:          {len(duty)}")

    COLUMNS = ["nom", "adresse", "telephone", "ville", "delegation",
               "horaires", "statut", "latitude", "longitude",
               "type_garde", "gouvernorat", "source"]

    save_json("pharmacies_all.json",   pharmacies)
    save_json("pharmacies_day.json",   day)
    save_json("pharmacies_night.json", night)
    save_json("pharmacies_duty.json",  duty)
    save_csv("pharmacies_all.csv",     pharmacies, COLUMNS)

    save_json("summary.json", {
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "med.tn",
        "duration_seconds": elapsed,
        "totals": {
            "all": len(pharmacies),
            "day": len(day),
            "night": len(night),
            "duty": len(duty),
        }
    })

    print("\n📁 Files saved in ./output/")


if __name__ == "__main__":
    main()
