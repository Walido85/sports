import asyncio
import json
import os
import random
import time
from typing import List, Dict

from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from google.cloud import firestore
from google.oauth2 import service_account

# --- FIRESTORE (your exact config + 'test' collection) ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("No FIREBASE_CREDENTIALS found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project='tunisia-radios-d7aa8', credentials=credentials, database='walid')
print("Firestore connected (database='walid', collection='test').")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
]

async def scrape_flashscore_live(url: str, doc_name: str):
    for attempt in range(3):
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
                context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
                page = await context.new_page()
                await stealth_async(page)

                print(f"[{attempt+1}/3] Loading {url}")
                await page.goto(url, wait_until="networkidle", timeout=60000)

                # Try old selector first, then fallback + debug
                try:
                    await page.wait_for_selector('.event__match', timeout=20000)
                    matches = await page.query_selector_all('.event__match')
                except:
                    print("Selector not found → saving debug files")
                    await page.screenshot(path=f"debug_{doc_name}.png")
                    with open(f"debug_{doc_name}_source.html", "w", encoding="utf-8") as f:
                        f.write(await page.content())
                    raise

                live_data = []
                for match in matches:
                    try:
                        home = await match.query_selector('.event__participant--home')
                        away = await match.query_selector('.event__participant--away')
                        score_elems = await match.query_selector_all('.event__score')
                        time_elem = await match.query_selector('.event__time')

                        live_data.append({
                            "home": await home.inner_text() if home else "N/A",
                            "away": await away.inner_text() if away else "N/A",
                            "live_score": f"{await score_elems[0].inner_text()} - {await score_elems[1].inner_text()}" if len(score_elems) >= 2 else "N/A",
                            "current_minute": await time_elem.inner_text() if time_elem else ""
                        })
                    except:
                        continue

                await browser.close()
                print(f"Extracted {len(live_data)} matches")
                return live_data

        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            if attempt == 2:
                raise
            await asyncio.sleep(8)

    return []

async def save_to_firestore(data: List[Dict], doc_name: str):
    if data:
        db.collection('test').document(doc_name).set({"matches": data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"Saved to test/{doc_name}")

async def main():
    urls = {
        "flashscore_live_tunisia": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-1/",
        "flashscore_live_premier_league": "https://www.flashscore.com/football/england/premier-league/"
    }
    for doc_name, url in urls.items():
        data = await scrape_flashscore_live(url, doc_name)
        await save_to_firestore(data, doc_name)

if __name__ == "__main__":
    asyncio.run(main())
    print("✅ Run finished.")
