import asyncio
import json
import os
import random
from typing import List, Dict

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

# --- FIRESTORE (your exact config) ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("No FIREBASE_CREDENTIALS found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project='tunisia-radios-d7aa8', credentials=credentials, database='walid')
print("Firestore connected → collection 'test'")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
]

# === ALL LEAGUES YOU WANTED (best of the best) ===
LEAGUES = [
    {"key": "tunisia_ligue1",          "name": "Tunisia Ligue 1",          "url": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-1/",          "standings_url": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-1/standings/"},
    {"key": "tunisia_ligue2",          "name": "Tunisia Ligue 2",          "url": "https://www.flashscore.com/football/tunisia/ligue-2/",                      "standings_url": "https://www.flashscore.com/football/tunisia/ligue-2/standings/"},
    {"key": "tunisia_cup",             "name": "Tunisia Cup",              "url": "https://www.flashscore.com/football/tunisia/tunisia-cup/",                   "standings_url": None},
    {"key": "premier_league",          "name": "Premier League",           "url": "https://www.flashscore.com/football/england/premier-league/",               "standings_url": "https://www.flashscore.com/football/england/premier-league/standings/"},
    {"key": "uefa_champions_league",   "name": "UEFA Champions League",    "url": "https://www.flashscore.com/football/europe/champions-league/",               "standings_url": "https://www.flashscore.com/football/europe/champions-league/standings/"},
    {"key": "caf_champions_league",    "name": "CAF Champions League",     "url": "https://www.flashscore.com/football/africa/caf-champions-league/",            "standings_url": "https://www.flashscore.com/football/africa/caf-champions-league/standings/"},
]

async def scrape_matches(page, doc_name: str):
    """Scrape Live + Fixtures + Results from one page load (very efficient)"""
    await page.wait_for_selector('.event__match', timeout=30000)
    matches = await page.query_selector_all('.event__match')

    live_data = []
    fixtures_data = []
    results_data = []

    for match in matches:
        try:
            home = await match.query_selector('.event__participant--home')
            away = await match.query_selector('.event__participant--away')
            
            home_text = await home.inner_text() if home else "N/A"
            away_text = await away.inner_text() if away else "N/A"

            # Score
            score_elems = await match.query_selector_all('.event__score')
            if len(score_elems) >= 2:
                score = f"{await score_elems[0].inner_text()} - {await score_elems[1].inner_text()}"
            else:
                score = "-- - --"

            # Time / status
            time_elem = await match.query_selector('.event__time')
            current_minute = await time_elem.inner_text() if time_elem else ""

            match_dict = {
                "home": home_text.strip(),
                "away": away_text.strip(),
                "live_score": score.strip(),
                "current_minute": current_minute.strip()
            }

            # Classify cleanly
            if "FT" in current_minute or "pen" in current_minute.lower() or ("'" in current_minute and score != "-- - --"):
                results_data.append(match_dict)          # Finished
            elif "'" in current_minute or "live" in current_minute.lower():
                live_data.append(match_dict)             # Live
            else:
                fixtures_data.append(match_dict)         # Upcoming

        except:
            continue

    # Save 3 separate clean documents
    if live_data:
        db.collection('test').document(f"flashscore_{doc_name}_live").set({"matches": live_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(live_data)} LIVE → test/flashscore_{doc_name}_live")
    if fixtures_data:
        db.collection('test').document(f"flashscore_{doc_name}_fixtures").set({"matches": fixtures_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(fixtures_data)} FIXTURES → test/flashscore_{doc_name}_fixtures")
    if results_data:
        db.collection('test').document(f"flashscore_{doc_name}_results").set({"matches": results_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(results_data)} RESULTS → test/flashscore_{doc_name}_results")

    return len(live_data) + len(fixtures_data) + len(results_data)

async def scrape_standings(page, doc_name: str):
    """Scrape standings table"""
    try:
        await page.wait_for_selector('.table__row, .standings__row', timeout=15000)
        rows = await page.query_selector_all('.table__row, .standings__row')
        
        table = []
        for row in rows:
            cells = await row.query_selector_all('div, span')
            texts = [await c.inner_text() for c in cells if await c.inner_text()]
            if len(texts) >= 8 and texts[0].strip().isdigit():
                table.append({
                    "position": texts[0].strip(),
                    "team": texts[1].strip(),
                    "played": texts[2].strip(),
                    "wins": texts[3].strip(),
                    "draws": texts[4].strip(),
                    "losses": texts[5].strip(),
                    "goals": texts[6].strip(),
                    "points": texts[7].strip()
                })
        if table:
            db.collection('test').document(f"flashscore_{doc_name}_standings").set({"table": table, "timestamp": firestore.SERVER_TIMESTAMP})
            print(f"✅ Saved {len(table)} standings → test/flashscore_{doc_name}_standings")
    except:
        print(f"⚠️ No standings for {doc_name}")

async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
        page = await context.new_page()

        for league in LEAGUES:
            print(f"\n🔄 Processing {league['name']}...")
            await page.goto(league["url"], wait_until="networkidle", timeout=60000)
            await scrape_matches(page, league["key"])

            if league["standings_url"]:
                await page.goto(league["standings_url"], wait_until="networkidle", timeout=60000)
                await scrape_standings(page, league["key"])

        await browser.close()
    print("\n🎉 ALL DONE – All data is now clean in Firestore collection 'test'")

if __name__ == "__main__":
    asyncio.run(main())
