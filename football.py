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
        
        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=10000)
        except:
            print("ℹ️ No live matches at this exact moment.")
            pass

        live_matches = await page.evaluate('''() => {
            const matches = [];
            const rows = document.querySelectorAll('div[data-id*="_mtc-r"]');
            
            for (const row of rows) {
                const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
                
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
    # LiveScore uses /standings/ for the league page table
    standings_url = url + "standings/" if not url.endswith("standings/") else url
    
    print(f"▶ Processing {name}...")
    
    fixtures = []
    results = []
    standings = []
    league_logo = ""

    # 1. Scrape Matches
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        
        try:
            logo_el = await page.wait_for_selector("div.qg img", timeout=5000)
            league_logo = await logo_el.get_attribute("src") if logo_el else ""
        except:
            pass

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
                }
                return { fixtures: fix, results: res };
            }''')
            fixtures = data.get("fixtures", [])
            results = data.get("results", [])
        except Exception:
            print(f"⚠️ No matches found for {name}")

        # 2. Scrape Standings Table
        await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('div.nj[data-id^="rw-"]', timeout=10000)
            standings = await page.evaluate('''() => {
                const table = [];
                // Find rows that have a team name (c-nm)
                const nameRows = Array.from(document.querySelectorAll('div.nj[data-id^="rw-"]')).filter(r => r.querySelector('div[data-id="c-nm"]'));
                
                for (const row of nameRows) {
                    const rowId = row.getAttribute('data-id'); // e.g. rw-4556
                    
                    let posText = row.querySelector('div[data-id="c-pos"]')?.innerText.trim() || "";
                    const match = posText.match(/\\d+/);
                    const pos = match ? match[0] : posText;
                    
                    const teamName = row.querySelector('div[data-id="c-nm"]')?.innerText.trim() || "";
                    const teamLogo = row.querySelector('img')?.src || "";
                    
                    if (!teamName) continue;
                    
                    // Find the sibling row with the same ID that holds the stats
                    const statsRows = Array.from(document.querySelectorAll(`div.nj[data-id="${rowId}"]`));
                    const statsRow = statsRows.find(r => r.querySelector('div[data-id$="_played"]'));
                    
                    let played="0", wins="0", draws="0", losses="0", gf="0", ga="0", gd="0", pts="0";
                    if (statsRow) {
                        played = statsRow.querySelector('div[data-id$="_played"]')?.innerText.trim() || "0";
                        wins = statsRow.querySelector('div[data-id$="_wins"]')?.innerText.trim() || "0";
                        draws = statsRow.querySelector('div[data-id$="_draws"]')?.innerText.trim() || "0";
                        losses = statsRow.querySelector('div[data-id$="_losses"]')?.innerText.trim() || "0";
                        gf = statsRow.querySelector('div[data-id$="_goalsFor"]')?.innerText.trim() || "0";
                        ga = statsRow.querySelector('div[data-id$="_goalsAgainst"]')?.innerText.trim() || "0";
                        gd = statsRow.querySelector('div[data-id$="_goalsDiff"]')?.innerText.trim() || "0";
                        pts = statsRow.querySelector('div[data-id$="_points"]')?.innerText.trim() || "0";
                    }
                    
                    // Only add if team isn't already in the list (prevents duplicates from home/away tabs)
                    if (!table.some(t => t.team === teamName)) {
                        table.push({
                            position: pos,
                            team: teamName,
                            team_logo: teamLogo,
                            played, wins, draws, losses, goals_for: gf, goals_against: ga, goal_diff: gd, points: pts
                        });
                    }
                }
                return table;
            }''')
        except Exception:
            print(f"⚠️ No standings found for {name}")

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
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            timezone_id="Africa/Tunis",
            locale="en-GB"
        )
        
        # Scrape Global Live Matches first
        await scrape_all_live(context)

        # Scrape Individual Leagues sequentially
        for league in LEAGUES:
            await scrape_league(context, league)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
