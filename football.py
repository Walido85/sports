import asyncio
import json
import os
import aiohttp
from datetime import datetime, timezone
from google.cloud import firestore
from google.oauth2 import service_account

# Set standard stdout to prevent buffering issues
import sys
sys.stdout.reconfigure(line_buffering=True)

DEBUG_STATS = {}

# ---------------------------------------------------------------------------
# FIREBASE SETUP
# ---------------------------------------------------------------------------
firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")
if not firebase_secret:
    print("❌ No FIREBASE_CREDENTIALS found.")
    sys.exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project="tunisia-radios-d7aa8", credentials=credentials, database="(default)")
print("✅ Firestore connected → collection 'football'")

# ---------------------------------------------------------------------------
# TARGET LEAGUES
# ---------------------------------------------------------------------------
# LiveScore organizes data by Competition ID (Ccd). 
# I have mapped the leagues you want to their exact LiveScore Ccd IDs.
LEAGUE_MAPPING = {
    "england-premier-league": "premier_league",
    "spain-laliga": "la_liga",
    "italy-serie-a": "serie_a",
    "germany-bundesliga": "bundesliga",
    "france-ligue-1": "ligue_1",
    "champions-league": "uefa_champions_league",
    "caf-champions-league": "caf_champions_league",
    "tunisia-ligue-1": "tunisia_ligue1",
    "tunisia-cup": "tunisia_cup"
}

LEAGUE_LOGOS = {
    "premier_league": "https://imgs.ysscores.com/championship/48/3411694791422.png",
    "serie_a": "https://imgs.ysscores.com/championship/48/6281692568873.png",
    "la_liga": "https://imgs.ysscores.com/championship/48/17656566406099.png",
    "ligue_1": "https://imgs.ysscores.com/championship/48/4371694791523.png",
    "bundesliga": "https://imgs.ysscores.com/championship/48/17693689565274.png",
    "uefa_champions_league": "https://imgs.ysscores.com/championship/48/1191723239247.png",
    "caf_champions_league": "https://imgs.ysscores.com/championship/48/4661694112676.png",
    "tunisia_ligue1": "https://imgs.ysscores.com/championship/48/7731690383928.png",
    "tunisia_cup": "https://imgs.ysscores.com/championship/48/6601696547585.png"
}

# ---------------------------------------------------------------------------
# HEADERS & HELPERS
# ---------------------------------------------------------------------------
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://www.livescore.com",
    "Referer": "https://www.livescore.com/"
}

def format_timestamp(eps: str) -> str:
    """LiveScore sends kickoff time like '20260511194500' -> Convert to standard ISO UTC string."""
    try:
        dt = datetime.strptime(eps, "%Y%m%d%H%M%S")
        dt = dt.replace(tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except:
        return ""

def determine_status(eps: str, epsc: str) -> str:
    """Determine if a match is a fixture, live, or result based on LiveScore's internal state codes."""
    # Eps is the status text (e.g., 'NS' = Not Started, 'FT' = Full Time, 'HT' = Half Time, '65' = Live Minute)
    if eps == "NS":
        return "fixture"
    elif eps in ["FT", "AET", "AP", "Canc.", "Postp.", "Aband."]:
        return "result"
    else:
        # Anything else (numbers, HT, Break) means the game is currently live
        return "live"

def format_match_time_and_score(match: dict, status: str) -> tuple:
    """Extract standard time string, score string, and live minute based on status."""
    minute = ""
    time_str = ""
    score = "-- - --"

    if status == "fixture":
        # Extract time from eps timestamp
        utc_ts = format_timestamp(match.get("Esd", ""))
        if utc_ts:
            time_str = datetime.strptime(utc_ts, "%Y-%m-%dT%H:%M:%SZ").strftime("%H:%M")
    
    elif status == "result":
        time_str = "FT"
        tr1 = match.get("Tr1", "")
        tr2 = match.get("Tr2", "")
        if tr1 != "" and tr2 != "":
             score = f"{tr1} - {tr2}"

    elif status == "live":
        # LiveScore puts the live minute directly in the "Eps" field (e.g. "65'")
        minute = match.get("Eps", "")
        if not minute.endswith("'") and minute.isdigit():
             minute += "'"
             
        tr1 = match.get("Tr1", "")
        tr2 = match.get("Tr2", "")
        if tr1 != "" and tr2 != "":
             score = f"{tr1} - {tr2}"

    return time_str, score, minute

# ---------------------------------------------------------------------------
# CORE SCRAPING LOGIC
# ---------------------------------------------------------------------------
async def scrape_live_api(session: aiohttp.ClientSession):
    """Hits the LiveScore API endpoint for currently live matches across all leagues."""
    print("▶ Scraping LIVE matches via API...")
    url = "https://prod-cdn-mev-api.livescore.com/v1/api/app/live/soccer/1?countryCode=IT&locale=en"
    
    try:
        async with session.get(url, headers=HEADERS) as response:
            if response.status != 200:
                print(f"⚠️ Live API returned status {response.status}")
                return []
            
            data = await response.json()
            stages = data.get("Stages", [])
            live_matches = []

            for stage in stages:
                # We only want to save live games for our target leagues
                comp_id = stage.get("Sn", "").lower().replace(" ", "-")
                country_id = stage.get("Cnm", "").lower().replace(" ", "-")
                
                # Check if this league is in our mapping list
                league_key = None
                for map_key, firestore_col in LEAGUE_MAPPING.items():
                    if map_key in comp_id or map_key in country_id + "-" + comp_id:
                        league_key = firestore_col
                        break
                
                if not league_key:
                    continue # Skip leagues we don't care about

                league_logo = LEAGUE_LOGOS.get(league_key, "")
                league_name = stage.get("Sn", "Unknown League")

                for match in stage.get("Events", []):
                    status = determine_status(match.get("Eps", ""), match.get("Epsc", ""))
                    if status != "live":
                        continue

                    home_team = match.get("T1", [{}])[0].get("Nm", "Unknown")
                    away_team = match.get("T2", [{}])[0].get("Nm", "Unknown")
                    
                    # LiveScore doesn't send logos in this payload, we rely on the frontend
                    # to use the team names, or we leave them blank
                    
                    time_str, score, minute = format_match_time_and_score(match, status)
                    utc_ts = format_timestamp(match.get("Esd", ""))

                    # Construct a URL for the match details on LiveScore
                    match_id = match.get("Eid", "")
                    url_slug = f"{home_team.lower().replace(' ', '-')}-vs-{away_team.lower().replace(' ', '-')}"
                    match_url = f"https://www.livescore.com/en/football/match/{match_id}/{url_slug}"

                    live_matches.append({
                        "home": home_team,
                        "away": away_team,
                        "home_logo": "", 
                        "away_logo": "",
                        "league": league_name,
                        "league_logo": league_logo,
                        "date": datetime.now(TUNIS_TZ).strftime("%A, %Y-%m-%d"),
                        "status": status,
                        "score": score,
                        "minute": minute,
                        "timestamp_utc": utc_ts,
                        "url": match_url
                    })

            # Save to Firestore
            save_live(live_matches)
            return live_matches

    except Exception as e:
         print(f"❌ Error scraping Live API: {e}")
         return []

async def scrape_daily_api(session: aiohttp.ClientSession, target_date: str):
    """Hits the LiveScore API endpoint for all matches (fixtures & results) on a specific date."""
    print(f"▶ Scraping daily matches for {target_date} via API...")
    url = f"https://prod-cdn-mev-api.livescore.com/v1/api/app/date/soccer/{target_date}/1?countryCode=IT&locale=en"
    
    # We will aggregate matches by our defined league keys
    league_data = {key: {"fixtures": [], "results": []} for key in LEAGUE_MAPPING.values()}
    
    try:
        async with session.get(url, headers=HEADERS) as response:
            if response.status != 200:
                print(f"⚠️ Daily API returned status {response.status}")
                return league_data
            
            data = await response.json()
            stages = data.get("Stages", [])

            for stage in stages:
                comp_id = stage.get("Sn", "").lower().replace(" ", "-")
                country_id = stage.get("Cnm", "").lower().replace(" ", "-")
                
                # Match LiveScore league to our Firestore collections
                league_key = None
                for map_key, firestore_col in LEAGUE_MAPPING.items():
                    if map_key in comp_id or map_key in country_id + "-" + comp_id:
                        league_key = firestore_col
                        break
                
                if not league_key:
                    continue 

                league_logo = LEAGUE_LOGOS.get(league_key, "")

                for match in stage.get("Events", []):
                    status = determine_status(match.get("Eps", ""), match.get("Epsc", ""))
                    
                    # We handle live games in the dedicated live function
                    if status == "live":
                        continue

                    home_team = match.get("T1", [{}])[0].get("Nm", "Unknown")
                    away_team = match.get("T2", [{}])[0].get("Nm", "Unknown")
                    
                    time_str, score, _ = format_match_time_and_score(match, status)
                    utc_ts = format_timestamp(match.get("Esd", ""))
                    
                    # Standardize date format for Firestore
                    match_dt = datetime.strptime(target_date, "%Y%m%d")
                    friendly_date = match_dt.strftime("%A, %Y-%m-%d")

                    match_id = match.get("Eid", "")
                    url_slug = f"{home_team.lower().replace(' ', '-')}-vs-{away_team.lower().replace(' ', '-')}"
                    match_url = f"https://www.livescore.com/en/football/match/{match_id}/{url_slug}"

                    match_obj = {
                        "home": home_team,
                        "away": away_team,
                        "home_logo": "", 
                        "away_logo": "",
                        "league_logo": league_logo,
                        "date": friendly_date,
                        "status": status,
                        "time": time_str,
                        "score": score,
                        "timestamp_utc": utc_ts,
                        "url": match_url
                    }

                    if status == "fixture":
                         league_data[league_key]["fixtures"].append(match_obj)
                    elif status == "result":
                         league_data[league_key]["results"].append(match_obj)
                         
    except Exception as e:
         print(f"❌ Error scraping Daily API: {e}")
         
    return league_data

# ---------------------------------------------------------------------------
# MAIN EXECUTION
# ---------------------------------------------------------------------------
async def main():
    async with aiohttp.ClientSession() as session:
        # 1. Scrape Live matches directly
        await scrape_live_api(session)

        # 2. Get today's date in YYYYMMDD format for the Daily API
        today_str = datetime.now(TUNIS_TZ).strftime("%Y%m%d")
        
        # 3. Scrape Fixtures and Results for today
        daily_data = await scrape_daily_api(session, today_str)

        # 4. Save the aggregated league data to Firestore
        for league_key in LEAGUE_MAPPING.values():
            
            # Find the full name for logging/saving purposes
            full_name = next((l["name"] for l in LEAGUES if l["key"] == league_key), league_key)
            logo = LEAGUE_LOGOS.get(league_key, "")
            
            # Standings are complex via API, so we initialize an empty struct for now
            # as LiveScore uses a separate undocumented endpoint for rankings
            standings_data = {} 
            
            save_league(full_name, {
                "league": full_name,
                "league_logo": logo,
                "fixtures": daily_data[league_key]["fixtures"],
                "results": daily_data[league_key]["results"],
                "standings": standings_data
            })

    print("\n" + "=" * 50)
    print("📊 FINAL SCRAPE SUMMARY:")
    print("=" * 50)
    for doc, info in DEBUG_STATS.items():
        print(f"  {doc.ljust(25)} : {info}")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
