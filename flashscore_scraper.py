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

# Exact headers from your screenshot (prevents 403)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_4 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://www.ysscores.com/",
    "X-Requested-With": "XMLHttpRequest",
}

LEAGUES = [
    # Tunisia - your exact links
    {"key": "tunisia_ligue1", "name": "Tunisia Ligue 1", 
     "url": "https://www.ysscores.com/ar/championship/76040/Tunisian-Professional-League-1", 
     "standings_url": "https://www.ysscores.com/ar/rank/901568/Tunisian-Professional-League-1"},
    {"key": "tunisia_ligue2", "name": "Tunisia Ligue 2", "url": "https://www.ysscores.com/ar/championship/76041/Tunisian-Professional-League-2", "standings_url": None},
    {"key": "tunisia_cup", "name": "Tunisia Cup", "url": "https://www.ysscores.com/ar/championship/76042/Tunisian-Cup", "standings_url": None},
    # Other leagues - Flashscore (most reliable)
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
    await page.goto(LEAGUES[0]["url"] if "tunisia" in doc_name else "https://www.flashscore.com/", wait_until="domcontentloaded", timeout=90000)
    await asyncio.sleep(10)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_matches.png")
    with open(f"debug/{doc_name}_matches.html", "w", encoding="utf-8") as f:
        f.write(await page.content())
    print(f"📸 Debug saved for {doc_name} matches")

    matches = await page.query_selector_all('.event__match, div.match, .match-row, [class*="match"], .event')
    live_data: List[Dict] = []
    fixtures_data: List[Dict] = []
    results_data: List[Dict] = []

    for match in matches:
        try:
            # Strongest home/away selectors (from all your debug files)
            home_elem = await match.query_selector('.event__participant--home, .home-team, .team-home, .team-name')
            away_elem = await match.query_selector('.event__participant--away, .away-team, .team-away, .team-name')
            home = clean_text(await home_elem.inner_text() if home_elem else "N/A")
            away = clean_text(await away_elem.inner_text() if away_elem else "N/A")

            if home == "N/A" or away == "N/A":
                names = await match.query_selector_all('.team-name, .event__participantName')
                if len(names) >= 2:
                    home = clean_text(await names[0].inner_text())
                    away = clean_text(await names[1].inner_text())

            score_elems = await match.query_selector_all('.event__score, .score, .result')
            score = f"{await score_elems[0].inner_text()} - {await score_elems[1].inner_text()}" if len(score_elems) >= 2 else "-- - --"

            time_elem = await match.query_selector('.event
