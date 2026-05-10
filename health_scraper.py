import json
import os
import csv
import time
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
    try:
        # Wait specifically for the text inside the actual cards to load, ignoring CSS classes
        page.wait_for_selector("text='Afficher le numéro'", timeout=15000)
    except:
        print("      ❌ Timeout: No pharmacy cards loaded on this page.")
        return []

    # Scroll to ensure all lazy-loaded cards render
    for _ in range(3):
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1000)

    # Locate and click all "Afficher le numéro" buttons to reveal hidden phone numbers
    buttons = page.locator("text='Afficher le numéro'")
    count = buttons.count()
    print(f"      Found {count} pharmacies. Revealing numbers...")
    
    for i in range(count):
        try:
            # Evaluate click via JS to bypass overlay interceptions
            buttons.nth(i).evaluate("node => node.click()")
            page.wait_for_timeout(300)
        except:
            continue
            
    page.wait_for_timeout(2000) # Give DOM time to update with the fetched numbers

    # Extract data using pure text-based DOM traversal
    extracted = page.evaluate('''() => {
        let results = [];
        
        // Find containers that have both "Pharmacie" and "Itinéraire" (Standard Med.tn card structure)
        let allElements = Array.from(document.querySelectorAll('div, li, article, section'));
        let cards = allElements.filter(el => {
            let text = el.innerText || "";
            return text.includes("Pharmacie") && 
                   text.includes("Itinéraire") &&
                   el.children.length > 2 && 
                   el.children.length < 30; // Prevents grabbing the entire page body
        });
        
        // Isolate the innermost container (the actual card)
        cards = cards.filter(card => !cards.some(other => card !== other && card.contains(other)));
        
        cards.forEach(card => {
            let text = card.innerText;
            let lines = text.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
            
            // Extract Name
            let name = lines.find(l => l.toLowerCase().includes('pharmacie')) || lines[0];
            
            // Extract Phone
            let phoneMatch = text.match(/(?:\\+?216)?[\\s.-]*([0-9]{2})[\\s.-]*([0-9]{3})[\\s.-]*([0-9]{3,4})/);
            let phone = phoneMatch ? phoneMatch[0].replace(/\\D/g, '') : "";
            if(phone.startsWith('216') && phone.length > 8) phone = phone.substring(3);
            
            // Extract Address (Usually located right above the 'Afficher le numéro' button)
            let address = "";
            for(let i = 0; i < lines.length; i++) {
                if((lines[i].includes('Afficher') || lines[i].includes('numéro')) && i > 0) {
                    address = lines[i-1];
                    break;
                }
            }
            if(!address || address === name) {
               let longLines = lines.filter(l => l.length > 15 && !l.match(/\\d{8}/) && l !== name);
               if(longLines.length > 0) address = longLines[0];
            }
            
            if(name && phone) {
                results.push({nom: name, adresse: address, telephone: phone});
            }
        });
        return results;
    }''')
    
    final_results = []
    for item in extracted:
        item["ville"] = city.replace("-", " ").title()
        item["type_garde"] = "Garde"
        item["source"] = "med.tn"
        item["scraped_at"] = time.strftime("%Y-%m-%d %H:%M")
        final_results.append(item)
        
    print(f"      ✅ Extracted {len(final_results)} pharmacies")
    return final_results

def main():
    start = time.time()
    all_pharmacies = []
    
    print("🚀 med.tn Scraper - Class-Agnostic Engine")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
            viewport={"width": 390, "height": 844}
        )
        page = context.new_page()

        for city in CITIES:
            # Med.tn routes 'grand-tunis' through the 'tunis' endpoint
            route = "tunis" if city == "grand-tunis" else city
            url = f"{BASE_URL}/pharmacie/garde/{route}"
            
            print(f"\n   🌐 {city.upper()} → {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
                pharmacies = parse_pharmacies(page, city)
                all_pharmacies.extend(pharmacies)
            except Exception as e:
                print(f"      ❌ Error {city}: {e}")

        browser.close()

    # Deduplicate by phone number to handle overlap
    seen = set()
    unique = [p for p in all_pharmacies if p["telephone"] and not (p["telephone"] in seen or seen.add(p["telephone"]))]

    elapsed = round(time.time() - start, 1)
    print(f"\n✅ Finished in {elapsed}s | Total unique: {len(unique)}")

    save_json("pharmacies_garde.json", unique)
    save_csv("pharmacies_garde.csv", unique)

if __name__ == "__main__":
    main()
