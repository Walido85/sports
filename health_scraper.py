import json
import os
import re
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        page = p.chromium.launch(headless=True).new_page()
        page.goto("https://www.med.tn/pharmacie/grand-tunis", wait_until="networkidle", timeout=30000)
        time.sleep(8)

        results = []
        cards = page.query_selector_all(".list__")

        for card in cards:
            text = card.inner_text()
            lines = [l.strip() for l in text.split('\n') if l.strip()]

            if len(lines) >= 2:
                name = lines[0]
                address = lines[1]
                # Aggressive phone search
                match = re.search(r'(\+?216)?\D*(\d{2})\D*(\d{3})\D*(\d{3,4})', text)
                phone = re.sub(r'\D', '', ''.join(match.groups())) if match else ""

                if name and phone:
                    results.append({
                        "nom": name,
                        "adresse": address,
                        "telephone": phone,
                        "ville": "Grand Tunis",
                        "type_garde": "Garde"
                    })

        print(f"Extracted {len(results)} pharmacies")

        with open("pharmacies_garde.json", "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()
