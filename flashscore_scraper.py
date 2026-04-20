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
    {"key": "tunisia_ligue1", "name": "Tunisia Ligue 1", "url": "https://www.sofascore.com/football/tunisia/ligue-professionnelle-1"},
    {"key": "tunisia_ligue2", "name": "Tunisia Ligue 2", "url": "https://www.sofascore.com/football/tunisia/ligue-2"},
    {"key": "tunisia_cup", "name": "Tunisia Cup", "url": "https://www.sofascore.com/football/tunisia/tunisia-cup"},
    {"key": "premier_league", "name": "Premier League", "url": "https://www.sofascore.com/football/england/premier-league"},
    {"key": "uefa_champions_league", "name": "UEFA Champions League", "url": "https://www.sofascore.com/football/europe/uefa-champions-league"},
    {"key": "caf_champions_league", "name": "CAF Champions League", "url": "https://www.sofascore.com/football/africa/caf-champions-league"},
]

def clean_text(text: str) -> str:
    text = text.strip()
    if len(text) < 2 or text in ["Pen", "pen", "FT", "AET", "PEN", "1", "2", "3", "4"]:
        return "N/A"
    if re.search(r'^\d+$', text):
        return "N/A"
    return text

async def scrape_matches(page, doc_name: str):
    await page.wait_for_selector('[data-testid="event-row"], .event-row, div[class*="match"]', timeout=30000)
    await asyncio.sleep(5)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_matches.png")
    with open(f"debug/{doc_name}_matches.html", "w", encoding="utf-8") as f:
        f.write(await page.content())
    print(f"📸 Debug saved for {doc_name} matches")

    matches = await page.query_selector_all('[data-testid="event-row"], .event-row, div[class*="match"]')
    live_data: List[Dict] = []
    fixtures_data: List[Dict] = []
    results_data: List[Dict] = []

    for match in matches:
        try:
            home = clean_text(await (await match.query_selector('[data-testid="team-name-home"], .home-team')).inner_text())
            away = clean_text(await (await match.query_selector('[data-testid="team-name-away"], .away-team')).inner_text())

            if home == "N/A" or away == "N/A":
                names = await match.query_selector_all('[data-testid="team-name"], .team-name')
                if len(names) >= 2:
                    home = clean_text(await names[0].inner_text())
                    away = clean_text(await names[1].inner_text())

            score_elem = await match.query_selector('[data-testid="score"], .score')
            score = await score_elem.inner_text() if score_elem else "-- - --"

            status_elem = await match.query_selector('[data-testid="status"], .status, .minute')
            status = await status_elem.inner_text() if status_elem else ""

            match_dict = {
                "home": home,
                "away": away,
                "date": "",
                "time": status,
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
        print(f"✅ Saved {len(live_data)} LIVE →
