import asyncio
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

# Strict Tunis Timezone
TUNIS_TZ = ZoneInfo("Africa/Tunis")

sys.stdout.reconfigure(line_buffering=True)

firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")
if not firebase_secret:
    print("❌ No FIREBASE_CREDENTIALS found.")
    sys.exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project="tunisia-radios-d7aa8", credentials=credentials, database="(default)")
print("✅ Firestore connected")

# Mapped to LiveScore URL paths
LEAGUES = [
    {"name": "Premier League", "url": "https://www.livescore.com/en/football/england/premier-league/"},
    {"name": "LaLiga", "url": "https://www.livescore.com/en/football/spain/laliga/"},
    {"name": "Serie A", "url": "https://www.livescore.com/en/football/italy/serie-a/"},
    {"name": "Bundesliga", "url": "https://www.livescore.com/en/football/germany/bundesliga/"},
    {"name": "Ligue 1", "url": "https://www.livescore.com/en/football/france/ligue-1/"},
    {"name": "Tunisia Ligue 1", "url": "https://www.livescore.com/en/football/tunisia/ligue-1/"}
]

async def scrape_livescore_league(context, league):
    page = await context.new_page()
    name = league["name"]
    print(f"▶ Scraping {name}...")
    
    try:
        await page.goto(league["url"], wait_until="networkidle", timeout=60000)
        
        # Select all match rows
        rows = await page.query_selector_all("div.yp.Dp")
        
        fixtures = []
        results = []
        
        for row in rows:
            # 1. Status / Time
            status_el = await row.query_selector("span.hw")
            status_text = (await status_el.inner_text()).strip() if status_el else ""
            
            # 2. Teams
            home_el = await row.query_selector("div.Hp div.Jp")
            away_el = await row.query_selector("div.Ip div.Jp")
            home_name = (await home_el.inner_text()).strip() if home_el else "Unknown"
            away_name = (await away_el.inner_text()).strip() if away_el else "Unknown"
            
            # 3. Logos
            home_img = await row.query_selector("div.Hp div.Sp img")
            away_img = await row.query_selector("div.Ip div.Sp img")
            home_logo = (await home_img.get_attribute("src")) if home_img else ""
            away_logo = (await away_img.get_attribute("src")) if away_img else ""
            
            # 4. Scores
            home_score_el = await row.query_selector("div.Op")
            away_score_el = await row.query_selector("div.Pp")
            h_score = (await home_score_el.inner_text()).strip() if home_score_el else ""
            a_score = (await away_score_el.inner_text()).strip() if away_score_el else ""

            match_data = {
                "home": home_name,
                "away": away_name,
                "home_logo": home_logo,
                "away_logo": away_logo,
                "updated_at": datetime.now(TUNIS_TZ).isoformat()
            }

            # Categorize based on confirmed LiveScore Status codes
            if status_text == "FT":
                match_data["status"] = "result"
                match_data["score"] = f"{h_score} - {a_score}"
                results.append(match_data)
            elif ":" in status_text:
                match_data["status"] = "fixture"
                match_data["time"] = status_text
                fixtures.append(match_data)

        # Save to Firestore
        db.collection("football").document(name).set({
            "league": name,
            "fixtures": fixtures,
            "results": results,
            "updated_at": datetime.now(TUNIS_TZ).isoformat()
        })
        print(f"✅ {name}: {len(fixtures)} Fix, {len(results)} Res")

    except Exception as e:
        print(f"❌ Error {name}: {e}")
    finally:
        await page.close()

async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        # Bypasses US server offset by forcing Tunis browser timezone
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            timezone_id="Africa/Tunis",
            locale="en-GB"
        )
        
        await asyncio.gather(*[scrape_livescore_league(context, l) for l in LEAGUES])
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
