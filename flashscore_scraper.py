import asyncio
import json
import os
import re
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
from google.cloud import firestore
from google.oauth2 import service_account

# === CONFIG ===
COLLECTION = "test"

LEAGUES = [
    {"key": "tunisia_ligue1", "name": "Tunisia Ligue 1", "url": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-1/"},
    {"key": "tunisia_ligue2", "name": "Tunisia Ligue 2", "url": "https://www.flashscore.com/football/tunisia/ligue-professionnelle-2/"},
    {"key": "tunisia_cup", "name": "Tunisia Cup", "url": "https://www.flashscore.com/football/tunisia/cup/"},
    {"key": "premier_league", "name": "Premier League", "url": "https://www.flashscore.com/football/england/premier-league/"},
    {"key": "uefa_champions_league", "name": "UEFA Champions League", "url": "https://www.flashscore.com/football/europe/champions-league/"},
    {"key": "caf_champions_league", "name": "CAF Champions League", "url": "https://www.flashscore.com/football/africa/caf-champions-league/"},
]

os.makedirs("debug", exist_ok=True)

def clean_team(text: str) -> str:
    if not text:
        return "N/A"
    text = text.strip()
    text = re.sub(r'\d{2}\.\d{2}\.|\d{2}:\d{2}|FT|HT|AET|PEN|pen|Pen|\d+-\d+|\d+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) < 3 or text in ["N/A", "-", "--", ""]:
        return "N/A"
    return text

async def scrape_matches(page, league_key: str):
    await page.wait_for_timeout(10000)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    
    matches = await page.query_selector_all('.event__match, [class*="event__match"]')
    
    data = {"matches": [], "timestamp": firestore.SERVER_TIMESTAMP}
    
    for match in matches:
        full_text = await match.inner_text()
        lines = [line.strip() for line in full_text.split('\n') if line.strip()]
        
        clean_lines = [clean_team(line) for line in lines if clean_team(line) != "N/A"]
        home = clean_lines[0] if len(clean_lines) >= 1 else "N/A"
        away = clean_lines[1] if len(clean_lines) >= 2 else "N/A"
        
        score_elem = await match.query_selector('.event__score')
        score = await score_elem.inner_text() if score_elem else "-- - --"
        
        time_elem = await match.query_selector('.event__time')
        time_str = await time_elem.inner_text() if time_elem else ""
        
        match_dict = {
            "home": home,
            "away": away,
            "live_score": score.strip(),
            "current_minute": time_str.strip(),
            "date": "", "time": "", "status": ""
        }
        data["matches"].append(match_dict)
    
    db = firestore.Client()
    doc_ref = db.collection(COLLECTION).document(f"flashscore_{league_key}_fixtures")
    doc_ref.set(data)
    print(f"✅ Saved {len(data['matches'])} matches → flashscore_{league_key}_fixtures")
    
    with open(f"debug/debug_{league_key}_matches.html", "w", encoding="utf-8") as f:
        f.write(await page.content())
    await page.screenshot(path=f"debug/debug_{league_key}_matches.png")

async def main():
    creds = json.loads(os.environ["FIREBASE_CREDENTIALS"])
    credentials = service_account.Credentials.from_service_account_info(creds)
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await stealth_async(page)   # ← FIXED LINE
        
        for league in LEAGUES:
            print(f"Processing {league['name']}...")
            await page.goto(league["url"], wait_until="networkidle")
            await scrape_matches(page, league["key"])
        
        await browser.close()
    print("Run completed")

if __name__ == "__main__":
    asyncio.run(main())
