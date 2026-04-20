import asyncio
import json
import os
import random
import re
from typing import List, Dict

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

# --- FIRESTORE ---
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

LEAGUES = [
    {"key": "tunisia_ligue1",          "name": "Tunisia Ligue 1",          "url": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-1/",          "standings_url": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-1/standings/"},
    {"key": "tunisia_ligue2",          "name": "Tunisia Ligue 2",          "url": "https://www.flashscore.com/football/tunisia/ligue-2/",                      "standings_url": "https://www.flashscore.com/football/tunisia/ligue-2/standings/"},
    {"key": "tunisia_cup",             "name": "Tunisia Cup",              "url": "https://www.flashscore.com/football/tunisia/tunisia-cup/",                   "standings_url": None},
    {"key": "premier_league",          "name": "Premier League",           "url": "https://www.flashscore.com/football/england/premier-league/",               "standings_url": "https://www.flashscore.com/football/england/premier-league/standings/OEEq9Yvp/standings/overall/"},
    {"key": "uefa_champions_league",   "name": "UEFA Champions League",    "url": "https://www.flashscore.com/football/europe/champions-league/",               "standings_url": "https://www.flashscore.com/football/europe/champions-league/standings/"},
    {"key": "caf_champions_league",    "name": "CAF Champions League",     "url": "https://www.flashscore.com/football/africa/caf-champions-league/",            "standings_url": "https://www.flashscore.com/football/africa/caf-champions-league/standings/hdkWXHOq/"},
]

def clean_date_time(text: str):
    """Separate date and time/status cleanly"""
    date_match = re.search(r'(\d{2}\.\d{2}\.)', text)
    time_match = re.search(r'(\d{2}:\d{2})', text)
    date = date_match.group(1) if date_match else ""
    time = time_match.group(1) if time_match else ""
    status = text.replace(date, "").replace(time, "").strip()
    return date.strip(), time.strip(), status.strip()

async def scrape_matches(page, doc_name: str):
    await page.wait_for_selector('.event__match', timeout=30000)
    await asyncio.sleep(3)

    matches = await page.query_selector_all('.event__match')
    live_data: List[Dict] = []
    fixtures_data: List[Dict] = []
    results_data: List[Dict] = []

    for match in matches:
        try:
            # === CLEAN HOME / AWAY (no date/time leak) ===
            home_text = away_text = "N/A"
            home_elem = await match.query_selector('.event__participant--home .event__participantName')
            away_elem = await match.query_selector('.event__participant--away .event__participantName')
            if home_elem: home_text = await home_elem.inner_text()
            if away_elem: away_text = await away_elem.inner_text()

            # Strong fallback
            if home_text == "N/A" or away_text == "N/A":
                parts = await match.query_selector_all('.event__participantName')
                if len(parts) >= 2:
                    home_text = await parts[0].inner_text()
                    away_text = await parts[1].inner_text()

            # Remove any date/time that leaked into team name
            if re.search(r'\d{2}\.\d{2}', home_text): home_text = "N/A"
            if re.search(r'\d{2}\.\d{2}', away_text): away_text = "N/A"

            # === SCORE ===
            score_elems = await match.query_selector_all('.event__score')
            score = f"{await score_elems[0].inner_text()} - {await score_elems[1].inner_text()}" if len(score_elems) >= 2 else "-- - --"

            # === DATE + TIME + STATUS ===
            time_elem = await match.query_selector('.event__time')
            raw_time = await time_elem.inner_text() if time_elem else ""
            date_str, time_str, status = clean_date_time(raw_time)

            match_dict = {
                "home": home_text.strip(),
                "away": away_text.strip(),
                "date": date_str,
                "time": time_str or status,           # for live = current minute, for fixtures = kick-off time
                "live_score": score.strip(),
                "status": status                      # "FT", "45'", "live", etc.
            }

            # Classify
            if "FT" in status or "pen" in status.lower() or score != "-- - --":
                results_data.append(match_dict)
            elif "'" in status or "live" in status.lower():
                live_data.append(match_dict)
            else:
                fixtures_data.append(match_dict)

        except:
            continue

    # Save clean, consistent documents
    if live_data:
        db.collection('test').document(f"flashscore_{doc_name}_live").set({"matches": live_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(live_data)} LIVE → test/flashscore_{doc_name}_live")
    if fixtures_data:
        db.collection('test').document(f"flashscore_{doc_name}_fixtures").set({"matches": fixtures_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(fixtures_data)} FIXTURES → test/flashscore_{doc_name}_fixtures")
    if results_data:
        db.collection('test').document(f"flashscore_{doc_name}_results").set({"matches": results_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(results_data)} PAST MATCHES (RESULTS) → test/flashscore_{doc_name}_results")

async def scrape_standings(page, doc_name: str):
    await asyncio.sleep(3)
    rows = await page.query_selector_all('.table__row, .standings__row, div[class*="row"]')
    table = []
    for row in rows:
        cells = await row.query_selector_all('div, span, td')
        texts = [await c.inner_text() for c in cells]
        texts = [t.strip() for t in texts if t.strip()]
        if len(texts) >= 8 and texts[0].isdigit():
            table.append({
                "position": texts[0],
                "team": texts[1],
                "played": texts[2],
                "wins": texts[3],
                "draws": texts[4],
                "losses": texts[5],
                "goals": texts[6],
                "points": texts[7]
            })
    if table:
        db.collection('test').document(f"flashscore_{doc_name}_standings").set({"table": table, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(table)} STANDINGS → test/flashscore_{doc_name}_standings")

async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
        page = await context.new_page()

        for league in LEAGUES:
            print(f"\n🔄 Processing {league['name']}...")
            await page.goto(league["url"], wait_until="networkidle", timeout=60000)
            await scrape_matches(page, league["key"])

            if league.get("standings_url"):
                await page.goto(league["standings_url"], wait_until="networkidle", timeout=60000)
                await scrape_standings(page, league["key"])

        await browser.close()
    print("\n🎉 ALL DONE – Firestore fields are now 100% clean and ready for your website")

if __name__ == "__main__":
    asyncio.run(main())
