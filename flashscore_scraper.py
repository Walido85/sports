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
    {"key": "tunisia_ligue1", "name": "Tunisia Ligue 1", "url": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-1/", "standings_url": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-1/standings/"},
    {"key": "tunisia_ligue2", "name": "Tunisia Ligue 2", "url": "https://www.flashscore.com/football/tunisia/ligue-2/", "standings_url": "https://www.flashscore.com/football/tunisia/ligue-2/standings/"},
    {"key": "tunisia_cup", "name": "Tunisia Cup", "url": "https://www.flashscore.com/football/tunisia/tunisia-cup/", "standings_url": None},
    {"key": "premier_league", "name": "Premier League", "url": "https://www.flashscore.com/football/england/premier-league/", "standings_url": "https://www.flashscore.com/football/england/premier-league/standings/OEEq9Yvp/standings/overall/"},
    {"key": "uefa_champions_league", "name": "UEFA Champions League", "url": "https://www.flashscore.com/football/europe/champions-league/", "standings_url": "https://www.flashscore.com/football/europe/champions-league/standings/"},
    {"key": "caf_champions_league", "name": "CAF Champions League", "url": "https://www.flashscore.com/football/africa/caf-champions-league/", "standings_url": "https://www.flashscore.com/football/africa/caf-champions-league/standings/hdkWXHOq/"},
]

def clean_text(text: str) -> str:
    text = text.strip()
    if len(text) < 2 or text in ["Pen", "pen", "FT", "AET", "PEN", "1", "2", "3", "4"]:
        return "N/A"
    if re.search(r'^\d+$', text):
        return "N/A"
    return text

async def scrape_matches(page, doc_name: str):
    print(f"   ⏳ Loading matches for {doc_name}...")
    await page.wait_for_load_state("networkidle", timeout=90000)
    await asyncio.sleep(8)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_matches.png")
    with open(f"debug/{doc_name}_matches.html", "w", encoding="utf-8") as f:
        f.write(await page.content())
    print(f"📸 Debug saved for {doc_name} matches")

    matches = await page.query_selector_all('.event__match')
    live_data: List[Dict] = []
    fixtures_data: List[Dict] = []
    results_data: List[Dict] = []

    for match in matches:
        try:
            home = clean_text(await (await match.query_selector('.event__participant--home')).inner_text())
            away = clean_text(await (await match.query_selector('.event__participant--away')).inner_text())

            if home == "N/A" or away == "N/A":
                names = await match.query_selector_all('.event__participantName')
                if len(names) >= 2:
                    home = clean_text(await names[0].inner_text())
                    away = clean_text(await names[1].inner_text())

            score_elems = await match.query_selector_all('.event__score')
            score = f"{await score_elems[0].inner_text()} - {await score_elems[1].inner_text()}" if len(score_elems) >= 2 else "-- - --"

            time_elem = await match.query_selector('.event__time')
            raw = await time_elem.inner_text() if time_elem else ""
            date_match = re.search(r'(\d{2}\.\d{2}\.)', raw)
            time_match = re.search(r'(\d{2}:\d{2})', raw)
            date_str = date_match.group(1) if date_match else ""
            time_str = time_match.group(1) if time_match else ""
            status = raw.replace(date_str, "").replace(time_str, "").strip()

            match_dict = {
                "home": home,
                "away": away,
                "date": date_str,
                "time": time_str or status,
                "live_score": score,
                "status": status
            }

            if "FT" in status.upper() or "PEN" in status.upper() or score != "-- - --":
                results_data.append(match_dict)
            elif "'" in status or "live" in status.lower():
                live_data.append(match_dict)
            else:
                fixtures_data.append(match_dict)

        except:
            continue

    if live_data:
        db.collection('test').document(f"flashscore_{doc_name}_live").set({"matches": live_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(live_data)} LIVE → flashscore_{doc_name}_live")
    if fixtures_data:
        db.collection('test').document(f"flashscore_{doc_name}_fixtures").set({"matches": fixtures_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(fixtures_data)} FIXTURES → flashscore_{doc_name}_fixtures")
    if results_data:
        db.collection('test').document(f"flashscore_{doc_name}_results").set({"matches": results_data, "timestamp": firestore.SERVER_TIMESTAMP})
        print(f"✅ Saved {len(results_data)} RESULTS → flashscore_{doc_name}_results")

async def scrape_standings(page, doc_name: str):
    print(f"   ⏳ Loading standings for {doc_name}...")
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_standings.png")
    with open(f"debug/{doc_name}_standings.html", "w", encoding="utf-8") as f:
        f.write(await page.content())
    print(f"📸 Debug saved for {doc_name} standings")

    rows = await page.query_selector_all('tr.table__row')
    table = []
    for row in rows:
        cells = await row.query_selector_all('td, .table__cell, div, span')
        texts = [clean_text(await c.inner_text()) for c in cells]
        texts = [t for t in texts if t != "N/A"]
        if len(texts) >= 8 and texts[0].replace('.', '').strip().isdigit():
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
        print(f"✅ Saved {len(table)} STANDINGS → flashscore_{doc_name}_standings")
    else:
        print(f"⚠️ No standings for {doc_name}")

async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = await browser.new_context(user_agent=random.choice(USER_AGENTS))
        page = await context.new_page()

        for league in LEAGUES:
            print(f"\n🔄 Processing {league['name']}...")
            try:
                await page.goto(league["url"], wait_until="networkidle", timeout=90000)
                await scrape_matches(page, league["key"])
                if league.get("standings_url"):
                    await page.goto(league["standings_url"], wait_until="networkidle", timeout=90000)
                    await scrape_standings(page, league["key"])
            except Exception as e:
                print(f"⚠️ Error processing {league['name']}: {e}")
                continue

        await browser.close()
    print("\n🎉 Run completed – check Firestore 'test' collection")

if __name__ == "__main__":
    asyncio.run(main())
