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

# Targeted LiveScore URLs
# Notice we use the base URL for matches and will append "standings/" for the table
LEAGUES = [
    {
        "name": "Tunisia Ligue 1",
        "url": "https://www.livescore.com/en/football/tunisia/ligue-i/"
    },
    {
        "name": "Premier League", 
        "url": "https://www.livescore.com/en/football/england/premier-league/"
    },
    {
        "name": "LaLiga", 
        "url": "https://www.livescore.com/en/football/spain/laliga/"
    },
    {
        "name": "Serie A", 
        "url": "https://www.livescore.com/en/football/italy/serie-a/"
    },
    {
        "name": "Bundesliga", 
        "url": "https://www.livescore.com/en/football/germany/bundesliga/"
    },
    {
        "name": "Ligue 1", 
        "url": "https://www.livescore.com/en/football/france/ligue-1/"
    },
    {
        "name": "UEFA Champions League", 
        "url": "https://www.livescore.com/en/football/champions-league/"
    },
    {
        "name": "CAF Champions League", 
        "url": "https://www.livescore.com/en/football/caf-champions-league/"
    }
]

async def scrape_matches(page, url):
    """Scrapes Fixtures, Results, and Live matches from the main league page."""
    fixtures = []
    results = []
    live = []
    league_logo = ""
    
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    
    # Extract League Logo dynamically from the page header
    try:
        logo_el = await page.wait_for_selector("div.qg img", timeout=10000)
        league_logo = await logo_el.get_attribute("src") if logo_el else ""
    except Exception:
        pass

    try:
        await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=15000)
        rows = await page.query_selector_all('div[data-id*="_mtc-r"]')
        
        for row in rows:
            try:
                # Time/Status
                status_el = await row.query_selector('span[data-id*="st-tm"]')
                status_text = (await status_el.inner_text()).strip() if status_el else ""
                
                # Team Names
                home_el = await row.query_selector('div[data-id*="hm-tm-nm"]')
                away_el = await row.query_selector('div[data-id*="aw-tm-nm"]')
                if not home_el or not away_el: 
                    continue
                
                home_name = (await home_el.inner_text()).strip()
                away_name = (await away_el.inner_text()).strip()
                
                # Team Logos
                home_img = await row.query_selector("div.Hp div.Sp img")
                away_img = await row.query_selector("div.Ip div.Sp img")
                home_logo = (await home_img.get_attribute("src")) if home_img else ""
                away_logo = (await away_img.get_attribute("src")) if away_img else ""
                
                # Scores
                h_score_el = await row.query_selector('div[data-id*="hm-sc"]')
                a_score_el = await row.query_selector('div[data-id*="aw-sc"]')
                h_score = (await h_score_el.inner_text()).strip() if h_score_el else ""
                a_score = (await a_score_el.inner_text()).strip() if a_score_el else ""

                match_data = {
                    "home": home_name,
                    "away": away_name,
                    "home_logo": home_logo,
                    "away_logo": away_logo,
                    "updated_at": datetime.now(TUNIS_TZ).isoformat()
                }

                # Status Logic
                if "FT" in status_text or "AET" in status_text or "Canc" in status_text or "Postp" in status_text:
                    match_data["status"] = "result"
                    match_data["score"] = f"{h_score} - {a_score}" if h_score and a_score else "-- - --"
                    results.append(match_data)
                elif ":" in status_text:
                    match_data["status"] = "fixture"
                    match_data["time"] = status_text
                    fixtures.append(match_data)
                elif "'" in status_text or "HT" in status_text or "Break" in status_text:
                    match_data["status"] = "live"
                    match_data["score"] = f"{h_score} - {a_score}"
                    match_data["minute"] = status_text
                    live.append(match_data)

            except Exception:
                continue

    except Exception as e:
        print(f"⚠️ Could not load matches for {url}: {e}")

    return league_logo, fixtures, results, live

async def scrape_standings(page, url):
    """Scrapes the league standings table."""
    standings = []
    standings_url = url + "standings/"
    
    try:
        await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_selector('div.nj[data-id^="rw-"]', timeout=15000)
        
        rows = await page.query_selector_all('div.nj[data-id^="rw-"]')
        
        for row in rows:
            try:
                # Rank / Position
                pos_el = await row.query_selector('div[data-id="c-pos"]')
                # Remove extra text like "Relegation" or "Champions League" inside the position box
                raw_pos = (await pos_el.inner_text()).strip() if pos_el else ""
                pos = re.search(r'\d+', raw_pos).group() if re.search(r'\d+', raw_pos) else raw_pos

                # Team Name
                nm_el = await row.query_selector('div[data-id="c-nm"]')
                team_name = (await nm_el.inner_text()).strip() if nm_el else "Unknown"

                # Team Logo
                img_el = await row.query_selector('div[data-id="c-nm"] img')
                team_logo = (await img_el.get_attribute("src")) if img_el else ""

                # Stats helper
                async def get_stat(data_suffix):
                    el = await row.query_selector(f'div[data-id$="{data_suffix}"]')
                    return (await el.inner_text()).strip() if el else "0"

                standings.append({
                    "position": pos,
                    "team": team_name,
                    "team_logo": team_logo,
                    "played": await get_stat("_played"),
                    "wins": await get_stat("_wins"),
                    "draws": await get_stat("_draws"),
                    "losses": await get_stat("_losses"),
                    "goals_for": await get_stat("_goalsFor"),
                    "goals_against": await get_stat("_goalsAgainst"),
                    "goal_diff": await get_stat("_goalsDiff"),
                    "points": await get_stat("_points")
                })
            except Exception:
                continue

    except Exception as e:
        print(f"⚠️ Could not load standings for {standings_url}")
        
    return standings

async def scrape_league_full(context, league):
    """Orchestrates scraping matches and standings for a single league."""
    page = await context.new_page()
    name = league["name"]
    url = league["url"]
    
    print(f"▶ Processing {name}...")
    
    league_logo, fixtures, results, live = await scrape_matches(page, url)
    standings = await scrape_standings(page, url)

    # Compile payload
    payload = {
        "league": name,
        "league_logo": league_logo,
        "fixtures": fixtures,
        "results": results,
        "live": live,
        "standings": {"type": "single", "table": standings} if standings else {},
        "updated_at": datetime.now(TUNIS_TZ).isoformat()
    }

    # Save to Firestore
    db.collection("football").document(name).set(payload)
    print(f"✅ Saved {name}: {len(fixtures)} Fix | {len(results)} Res | {len(live)} Live | {len(standings)} Teams in Table")
    
    await page.close()

async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        # Lock to Tunis timezone to get native match times from LiveScore
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            timezone_id="Africa/Tunis",
            locale="en-GB"
        )
        
        # Run sequentially or limited batches to avoid getting rate-limited by LiveScore
        for league in LEAGUES:
            await scrape_league_full(context, league)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
