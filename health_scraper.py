import json
import os
import time
import re
from playwright.sync_api import sync_playwright

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def main():
    print("🚀 DEBUG - Raw Card Content")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        page = context.new_page()
        
        url = "https://www.med.tn/pharmacie/grand-tunis"
        print(f"Opening {url}")
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(8)

        cards = page.query_selector_all(".list__")
        print(f"Found {len(cards)} .list__ cards")

        extracted = 0
        for i, card in enumerate(cards[:20]):
            full_text = card.inner_text().strip()
            print(f"\n--- CARD {i+1} ---\n{full_text}\n{'-'*80}")

            # Simple extraction
            lines = [line.strip() for line in full_text.split('\n') if line.strip()]
            name = next((line for line in lines if "pharmacie" in line.lower()), "Unknown")
            
            phone_match = re.search(r'(\+?216)?[\s.-]*(\d{2})[\s.-]*(\d{3})[\s.-]*(\d{3,4})', full_text)
            phone = re.sub(r'\D', '', ''.join(phone_match.groups())) if phone_match else ""

            if phone:
                extracted += 1
                print(f"✓ EXTRACTED → Name: {name} | Phone: {phone}")

        print(f"\nTotal extracted in this run: {extracted}")
        browser.close()

if __name__ == "__main__":
    main()
