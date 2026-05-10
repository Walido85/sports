import json
import os
from playwright.sync_api import sync_playwright
import re

OUTPUT_DIR = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def main():
    print("🚀 DEBUG - Raw Card Content")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64)").new_page()
        
        page.goto("https://www.med.tn/pharmacie/grand-tunis", wait_until="networkidle", timeout=30000)
        time.sleep(8)

        cards = page.query_selector_all(".list__")
        print(f"Found {len(cards)} .list__ cards")

        for i, card in enumerate(cards[:15]):
            text = card.inner_text().strip()
            print(f"\n--- CARD {i+1} ---\n{text}\n{'-'*60}")

        browser.close()

if __name__ == "__main__":
    main()
