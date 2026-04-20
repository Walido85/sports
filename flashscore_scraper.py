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

def is_valid_team_name(text: str) -> bool:
    text = text.strip()
    if len(text) < 3: return False
    if text in ["Pen", "pen", "FT", "AET", "PEN", "1", "2", "3", "4"]: return False
    if re.search(r'^\d+$', text): return False
    return True

async def scrape_matches(page, doc_name: str):
    await page.wait_for_selector('.event__match', timeout=30000)
    await asyncio.sleep(4)

    # Debug files for verification
    await page.screenshot(path=f"debug_{doc_name}_matches.png")
    with open(f"debug_{doc_name}_matches.html", "w", encoding="utf-8") as f:
        f.write(await page.content())
    print(f"📸 Debug files saved for {doc_name} (matches)")

    matches = await page.query_selector_all('.event__match')
    live_data: List[Dict] = []
    fixtures_data: List[Dict] = []
    results_data: List[Dict] = []

    for match in matches:
        try:
            home_text = away_text = "N/A"

            # Primary
            home_elem = await match.query_selector('.event__participant--home')
            away_elem = await match.query_selector('.event__participant--away')
            if home_elem:
                full = await home_elem.inner_text()
                for line in full.split('\n'):
                    if is_valid_team_name(line):
                        home_text = line.strip()
                        break
            if away_elem:
                full = await away_elem.inner_text()
                for line in full.split('\n'):
                    if is_valid_team_name(line):
                        away_text = line.strip()
                        break

            # Fallback
            if not is_valid_team_name(home_text) or not is_valid_team_name(away_text):
                names = await match.query_selector_all('.event__participantName')
                if len(names) >= 2:
                    home_text = await names[0].inner_text()
                    away_text = await names[1].inner_text()

            # Score
            score_elems = await match.query_selector_all('.event__score')
            score = f"{await score_elems[0].inner_text()} - {await score_elems[1].inner_text()}" if len(score_elems) >= 2 else "-- - --"

            # Date + Time + Status
            time_elem = await match.query_selector('.event__time')
            raw = await time_elem.inner_text() if time_elem else ""
            date_match = re.search(r'(\d{2}\.\d{2}\.)', raw)
            time_match = re.search(r'(\d{2}:\d{2})', raw)
            date_str = date_match.group(1) if date_match else ""
            time_str = time_match.group(1) if time_match else ""
            status = raw.replace(date_str, "").replace(time_str, "").strip()

            match_dict = {
                "home": home_text,
                "away": away_text,
                "date": date_str,
                "time": time_str or status,
                "live_score": score,
                "status": status
            }

            if "FT" in status or "pen" in status.lower() or "AET" in status or score != "-- - --":
                results_data.append(match_dict)
            elif "'" in status or "live" in status.lower():
                live_data.append(match_dict)
            else:
                fixtures_data.append(match_dict)

        except:
            continue

    if live_data:
        db.collection('test').document(f"flashscore_{doc_name}_live").set({"matches": live_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(live_data)} LIVE")
    if fixtures_data:
        db.collection('test').document(f"flashscore_{doc_name}_fixtures").set({"matches": fixtures_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(fixtures_data)} FIXTURES")
    if results_data:
        db.collection('test').document(f"flashscore_{doc_name}_results").set({"matches": results_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(results_data)} RESULTS")

async def scrape_standings(page, doc_name: str):
    await asyncio.sleep(3)

    # Debug for standings
    await page.screenshot(path=f"debug_{doc_name}_standings.png")
    with open(f"debug_{doc_name}_standings.html", "w", encoding="utf-8") as f:
        f.write(await page.content())
    print(f"📸 Debug files saved for {doc_name} (standings)")

    rows = await page.query_selector_all('tr.table__row, .table__row')

    table = []
    for row in rows:
        cells = await row.query_selector_all('td, div, span')
        texts = [await c.inner_text() for c in cells]
        texts = [t.strip() for t in texts if t.strip()]
        if len(texts) >= 8 and (texts[0].replace('.', '').strip().isdigit() or texts[0].strip().isdigit()):
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
    else:
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

            if league.get("standings_url"):
                await page.goto(league["standings_url"], wait_until="networkidle", timeout=60000)
                await scrape_standings(page, league["key"])

        await browser.close()
    print("\n🎉 Run completed – check GitHub Artifacts for debug files if needed")

if __name__ == "__main__":
    asyncio.run(main())
