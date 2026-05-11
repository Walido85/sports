import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

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
            const todayStr = new Date().toISOString().split('T')[0];
            
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
                    date: todayStr,
                    home: homeName,
                    away: awayName,
                    home_logo: homeLogo,
                    away_logo: awayLogo,
                    league: leagueName,
                    league_logo: leagueLogo,
                    status: "live",
                    score: (hScore && aScore) ? `${hScore} - ${aScore}` : "-- - --",
                    minute: statusText,
                    timezone: "UTC"
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
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    print(f"✅ Saved 'live': {len(live_matches)} matches")

async def scrape_league(context, league):
    page = await context.new_page()
    name = league["name"]
    url = league["url"]
    standings_url = url + "standings/" if not url.endswith("standings/") else url
    
    print(f"▶ Processing {name}...")
    
    fixtures = []
    results = []
    standings = []
    league_logo = ""

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
                const todayStr = new Date().toISOString().split('T')[0];
                
                for (const row of rows) {
                    const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
                    const homeName = row.querySelector('div[data-id*="hm-tm-nm"]')?.innerText.trim() || "";
                    const awayName = row.querySelector('div[data-id*="aw-tm-nm"]')?.innerText.trim() || "";
                    if (!homeName || !awayName) continue;

                    const homeLogo = row.querySelector('div.Hp div.Sp img')?.src || "";
                    const awayLogo = row.querySelector('div.Ip div.Sp img')?.src || "";
                    const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.trim() || "";
                    const aScore = row.querySelector('div[data-id*="aw-sc"]')?.innerText.trim() || "";
                    
                    let matchDate = "";
                    let currentElement = row;
                    const ignoreList = ['fixtures', 'results', 'matches', 'table', 'overview', 'news', 'all', 'home', 'away'];

                    while(currentElement && currentElement !== document.body) {
                        let pSibling = currentElement.previousElementSibling;
                        while(pSibling) {
                            let text = pSibling.innerText.trim().split('\\n')[0];
                            const lowerText = text.toLowerCase();
                            
                            if (text && text.length >= 3 && text.length <= 30 && !text.includes(':') && !ignoreList.includes(lowerText)) {
                                if (lowerText === 'today') {
                                    matchDate = todayStr;
                                } else if (lowerText === 'yesterday') {
                                    let d = new Date(); 
                                    d.setDate(d.getDate() - 1);
                                    matchDate = d.toISOString().split('T')[0];
                                } else if (lowerText === 'tomorrow') {
                                    let d = new Date(); 
                                    d.setDate(d.getDate() + 1);
                                    matchDate = d.toISOString().split('T')[0];
                                } else {
                                    matchDate = text;
                                }
                                break;
                            }
                            pSibling = pSibling.previousElementSibling;
                        }
                        if (matchDate) break;
                        currentElement = currentElement.parentElement;
                    }
                    
                    const matchObj = {
                        date: matchDate || todayStr,
                        home: homeName,
                        away: awayName,
                        home_logo: homeLogo,
                        away_logo: awayLogo,
                        timezone: "UTC"
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

        await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('div.nj[data-id^="rw-"]', timeout=10000)
            standings = await page.evaluate('''() => {
                const table = [];
                const seenTeams = new Set();
                
                const nameRows = Array.from(document.querySelectorAll('div.nj[data-id^="rw-"]')).filter(r => r.querySelector('div[data-id="c-nm"]'));
                
                for (const row of nameRows) {
                    const teamName = row.querySelector('div[data-id="c-nm"]')?.innerText.trim() || "";
                    if (!teamName) continue;
                    
                    if (seenTeams.has(teamName)) continue;
                    seenTeams.add(teamName);

                    const rowId = row.getAttribute('data-id'); 
                    
                    let posText = row.querySelector('div[data-id="c-pos"]')?.innerText.trim() || "";
                    const match = posText.match(/\\d+/);
                    const pos = match ? match[0] : posText;
                    
                    const teamLogo = row.querySelector('img')?.src || "";
                    
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
                    
                    table.push({
                        position: pos,
                        team: teamName,
                        team_logo: teamLogo,
                        played, wins, draws, losses, goals_for: gf, goals_against: ga, goal_diff: gd, points: pts
                    });
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
            "updated_at": datetime.now(timezone.utc).isoformat()
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
            timezone_id="UTC",
            locale="en-GB"
        )
        
        await scrape_all_live(context)

        for league in LEAGUES:
            await scrape_league(context, league)
            
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
