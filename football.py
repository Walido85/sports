import asyncio
import json
import os
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

LEAGUES = [
    {"name": "Tunisia Ligue 1", "url": "https://www.livescore.com/en/football/tunisia/ligue-i/"},
    {"name": "Premier League", "url": "https://www.livescore.com/en/football/england/premier-league/"},
    {"name": "LaLiga", "url": "https://www.livescore.com/en/football/spain/laliga/"},
    {"name": "Serie A", "url": "https://www.livescore.com/en/football/italy/serie-a/"},
    {"name": "Bundesliga", "url": "https://www.livescore.com/en/football/germany/bundesliga/"},
    {"name": "Ligue 1", "url": "https://www.livescore.com/en/football/france/ligue-1/"},
    {"name": "UEFA Champions League", "url": "https://www.livescore.com/en/football/champions-league/"},
    {"name": "CAF Champions League", "url": "https://www.livescore.com/en/football/caf-champions-league/"}
]

async def scrape_all_live(context):
    """Scrapes the global Live page and saves all active matches to a separate document."""
    page = await context.new_page()
    print("▶ Scraping Global LIVE matches...")
    
    live_matches = []
    try:
        await page.goto("https://www.livescore.com/en/football/live/", wait_until="domcontentloaded", timeout=60000)
        
        # Wait for matches to load, but don't crash if there are zero live games right now
        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=10000)
        except:
            print("ℹ️ No live matches at this exact moment.")
            pass

        # Use JS evaluate for speed and to grab the league header associated with each match
        live_matches = await page.evaluate('''() => {
            const matches = [];
            const rows = document.querySelectorAll('div[data-id*="_mtc-r"]');
            
            for (const row of rows) {
                const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
                
                // Only grab games that are actively playing (skip FT, Canc, etc if they linger)
                if (statusText === "FT" || statusText.includes("Canc") || statusText.includes("Postp") || statusText.includes(":")) {
                    continue;
                }
                
                const homeName = row.querySelector('div[data-id*="hm-tm-nm"]')?.innerText.trim() || "";
                const awayName = row.querySelector('div[data-id*="aw-tm-nm"]')?.innerText.trim() || "";
                if (!homeName || !awayName) continue;

                const homeLogo = row.querySelector('div.Hp div.Sp img')?.src || "";
                const awayLogo = row.querySelector('div.Ip div.Sp img')?.src || "";
                const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.trim() || "";
                const aScore = row.querySelector('div[data-id*="aw-sc"]')?.innerText.trim() || "";
                
                // Find the closest league header for this match
                const container = row.closest('div[data-index]');
                const leagueName = container ? (container.querySelector('div[data-id="st-hdr_stg"]')?.innerText.trim() || "Unknown") : "Unknown";
                const leagueLogo = container ? (container.querySelector('div.qg img')?.src || "") : "";

                matches.push({
                    home: homeName,
                    away: awayName,
                    home_logo: homeLogo,
                    away_logo: awayLogo,
                    league: leagueName,
                    league_logo: leagueLogo,
                    status: "live",
                    score: (hScore && aScore) ? `${hScore} - ${aScore}` : "-- - --",
                    minute: statusText
                });
            }
            return matches;
        }''')

    except Exception as e:
        print(f"❌ Error scraping Live: {e}")
    finally:
        await page.close()

    # Save globally to 'live' document
    db.collection("football").document("live").set({
        "matches": live_matches,
        "count": len(live_matches),
        "updated_at": datetime.now(TUNIS_TZ).isoformat()
    })
    print(f"✅ Saved 'live': {len(live_matches)} matches")

async def scrape_league(context, league):
    """Scrapes Fixtures, Results, and Standings for a specific league."""
    page = await context.new_page()
    name = league["name"]
    url = league["url"]
    standings_url = url + "table/" if not url.endswith("table/") else url
    
    print(f"▶ Processing {name}...")
    
    fixtures = []
    results = []
    standings = []
    league_logo = ""

    # 1. Scrape Matches (Fixtures & Results only, Live handled separately)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        # Get League Logo
        try:
            logo_el = await page.wait_for_selector("div.qg img", timeout=5000)
            league_logo = await logo_el.get_attribute("src") if logo_el else ""
        except:
            pass

        # Wait for matches, ignore timeout if cup/league has no games scheduled right now
        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=10000)
            data = await page.evaluate('''() => {
                const fix = [];
                const res = [];
                const rows = document.querySelectorAll('div[data-id*="_mtc-r"]');
                
                for (const row of rows) {
                    const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
                    const homeName = row.querySelector('div[data-id*="hm-tm-nm"]')?.innerText.trim() || "";
                    const awayName = row.querySelector('div[data-id*="aw-tm-nm"]')?.innerText.trim() || "";
                    if (!homeName || !awayName) continue;

                    const homeLogo = row.querySelector('div.Hp div.Sp img')?.src || "";
                    const awayLogo = row.querySelector('div.Ip div.Sp img')?.src || "";
                    const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.trim() || "";
                    const aScore = row.querySelector('div[data-id*="aw-sc"]')?.innerText.trim() || "";
                    
                    const matchObj = {
                        home: homeName,
                        away: awayName,
                        home_logo: homeLogo,
                        away_logo: awayLogo
                    };

                    if (statusText.includes("FT") || statusText.includes("AET") || statusText.includes("Canc") || statusText.includes("Postp")) {
                        matchObj.status = "result";
                        matchObj.score = (hScore && aScore) ? `${hScore} - ${aScore}` : "-- - --";
                        res.push(matchObj);
                    } else if (statusText.includes(":")) {
                        matchObj.status = "fixture";
                        matchObj.time = statusText;
                        fix.push(matchObj);
                    }
                    // Live matches skipped here as they are handled in global live scraper
                }
                return { fixtures: fix, results: res };
            }''')
            fixtures = data.get("fixtures", [])
            results = data.get("results", [])
        except Exception:
            print(f"⚠️ No matches found for {name}")

        # 2. Scrape Standings Table (Restricted to "All" tab to prevent duplication)
        await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        try:
            # Wait for specific "All" table wrapper
            await page.wait_for_selector('div[data-id="lt-tb-all"] div.nj[data-id^="rw-"]', timeout=10000)
            standings = await page.evaluate('''() => {
                const table = [];
                // STRICTLY target the 'All' tab to stop duplicating 40+ teams
                const rows = document.querySelectorAll('div[data-id="lt-tb-all"] div.nj[data-id^="rw-"]');
                
                for (const row of rows) {
                    let posText = row.querySelector('div[data-id="c-pos"]')?.innerText.trim() || "";
                    const match = posText.match(/\\d+/);
                    const pos = match ? match[0] : posText;
                    
                    const teamName = row.querySelector('div[data-id="c-nm"]')?.innerText.trim() || "";
                    const teamLogo = row.querySelector('div[data-id="c-nm"] img')?.src || "";
                    
                    if (!teamName) continue;

                    table.push({
                        position: pos,
                        team: teamName,
                        team_logo: teamLogo,
                        played: row.querySelector('div[data-id$="_played"]')?.innerText.trim() || "0",
                        wins: row.querySelector('div[data-id$="_wins"]')?.innerText.trim() || "0",
                        draws: row.querySelector('div[data-id$="_draws"]')?.innerText.trim() || "0",
                        losses: row.querySelector('div[data-id$="_losses"]')?.innerText.trim() || "0",
                        goals_for: row.querySelector('div[data-id$="_goalsFor"]')?.innerText.trim() || "0",
                        goals_against: row.querySelector('div[data-id$="_goalsAgainst"]')?.innerText.trim() || "0",
                        goal_diff: row.querySelector('div[data-id$="_goalsDiff"]')?.innerText.trim() || "0",
                        points: row.querySelector('div[data-id$="_points"]')?.innerText.trim() || "0"
                    });
                }
                return table;
            }''')
        except Exception:
            print(f"⚠️ No standings found for {name}")

        # Save League Document
        db.collection("football").document(name).set({
            "league": name,
            "league_logo": league_logo,
            "fixtures": fixtures,
            "results": results,
            "standings": {"type": "single", "table": standings} if standings else {},
            "updated_at": datetime.now(TUNIS_TZ).isoformat()
        })
        print(f"✅ Saved {name}: {len(fixtures)} Fix | {len(results)} Res | {len(standings)} Teams in Table")

    except Exception as e:
        print(f"❌ Error processing {name}: {e}")
    finally:
        await page.close()

async def main():
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        # Enforce Tunis Timezone so HH:MM fixtures match local time
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            timezone_id="Africa/Tunis",
            locale="en-GB"
        )
        
        # 1. Scrape Global Live Matches
        await scrape_all_live(context)

        # 2. Scrape Individual Leagues
        await asyncio.gather(*[scrape_league(context, l) for l in LEAGUES])
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
