import asyncio
import json
import os
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
    {"name": "CAF Champions League", "url": "https://www.livescore.com/en/football/africa/caf-champions-league/"}
]

LIVE_JS = """() => {
    const matches = [];
    const rows = document.querySelectorAll('div[data-id*="_mtc-r"]');
    for (const row of rows) {
        const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
        if (statusText === "FT" || statusText.includes("Canc") || statusText.includes("Postp") || statusText.includes(":")) continue;
        const homeName = row.querySelector('div[data-id*="hm-tm-nm"]')?.innerText.trim() || "";
        const awayName = row.querySelector('div[data-id*="aw-tm-nm"]')?.innerText.trim() || "";
        if (!homeName || !awayName) continue;
        const imgs = row.querySelectorAll('img');
        const homeLogo = imgs[0]?.src || "";
        const awayLogo = imgs[1]?.src || "";
        const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.trim() || "";
        const aScore = row.querySelector('div[data-id*="aw-sc"]')?.innerText.trim() || "";
        const container = row.closest('div[data-index]');
        const leagueName = container ? (container.querySelector('div[data-id="st-hdr_stg"]')?.innerText.trim() || "Unknown") : "Unknown";
        const leagueLogo = container ? (container.querySelector('div.al img.Ok')?.src || container.querySelector('img.Ok')?.src || "") : "";
        matches.push({
            home: homeName, away: awayName,
            home_logo: homeLogo, away_logo: awayLogo,
            league: leagueName, league_logo: leagueLogo,
            status: "live",
            score: (hScore && aScore) ? hScore + " - " + aScore : "-- - --",
            minute: statusText, timezone: "UTC"
        });
    }
    return matches;
}"""

MATCHES_JS = """() => {
    const fix = [];
    const res = [];
    const rows = document.querySelectorAll('div[data-id*="_mtc-r"]');
    for (const row of rows) {
        const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
        const homeName = row.querySelector('div[data-id*="hm-tm-nm"]')?.innerText.trim() || "";
        const awayName = row.querySelector('div[data-id*="aw-tm-nm"]')?.innerText.trim() || "";
        if (!homeName || !awayName) continue;
        const imgs = row.querySelectorAll('img');
        const homeLogo = imgs[0]?.src || "";
        const awayLogo = imgs[1]?.src || "";
        const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.trim() || "";
        const aScore = row.querySelector('div[data-id*="aw-sc"]')?.innerText.trim() || "";
        const matchDate = row.querySelector('span.jx')?.innerText.trim() || "";
        const matchObj = {
            home: homeName, away: awayName,
            home_logo: homeLogo, away_logo: awayLogo,
            date: matchDate, timezone: "UTC"
        };
        if (statusText.includes("FT") || statusText.includes("AET") || statusText.includes("Canc") || statusText.includes("Postp")) {
            matchObj.status = "result";
            matchObj.score = (hScore && aScore) ? hScore + " - " + aScore : "-- - --";
            res.push(matchObj);
        } else if (statusText.includes(":")) {
            matchObj.status = "fixture";
            matchObj.time = statusText;
            fix.push(matchObj);
        }
    }
    return { fixtures: fix, results: res };
}"""

STANDINGS_JS = """() => {
    const table = [];
    const rows = document.querySelectorAll('div[data-id^="rw-"]');
    for (const row of rows) {
        const rowId = row.getAttribute('data-id');
        const teamId = rowId.replace('rw-', '');
        if (!row.querySelector('div[data-id="c-nm"]')) continue;
        const posEl = row.querySelector('div[data-id="c-pos"]');
        let posText = posEl?.innerText?.trim() || "";
        const posMatch = posText.match(/\\d+/);
        const pos = posMatch ? posMatch[0] : posText;
        const teamLink = row.querySelector('div[data-id="c-nm"] a.ux');
        if (!teamLink) continue;
        const teamName = teamLink.innerText?.trim() || "";
        const teamLogo = teamLink.querySelector('div.vx img')?.src || "";
        if (!teamName) continue;

        let played="0", wins="0", draws="0", losses="0", gf="0", ga="0", gd="0", pts="0";
        const allTeamDivs = document.querySelectorAll('div[data-id^="' + teamId + '_"]');
        let foundSuffix = "";
        for (const d of allTeamDivs) {
            const did = d.getAttribute('data-id');
            if (did.endsWith('_played')) {
                foundSuffix = did.replace(teamId + '_', '').replace('_played', '');
                break;
            }
        }
        if (foundSuffix) {
            played = document.querySelector('div[data-id="' + teamId + '_' + foundSuffix + '_played"]')?.innerText?.trim() || "0";
            wins   = document.querySelector('div[data-id="' + teamId + '_' + foundSuffix + '_wins"]')?.innerText?.trim() || "0";
            draws  = document.querySelector('div[data-id="' + teamId + '_' + foundSuffix + '_draws"]')?.innerText?.trim() || "0";
            losses = document.querySelector('div[data-id="' + teamId + '_' + foundSuffix + '_losses"]')?.innerText?.trim() || "0";
            gf     = document.querySelector('div[data-id="' + teamId + '_' + foundSuffix + '_goalsFor"]')?.innerText?.trim() || "0";
            ga     = document.querySelector('div[data-id="' + teamId + '_' + foundSuffix + '_goalsAgainst"]')?.innerText?.trim() || "0";
            gd     = document.querySelector('div[data-id="' + teamId + '_' + foundSuffix + '_goalsDiff"]')?.innerText?.trim() || "0";
            pts    = document.querySelector('div[data-id="' + teamId + '_' + foundSuffix + '_points"]')?.innerText?.trim() || "0";
        }

        if (!table.some(t => t.team === teamName)) {
            table.push({
                position: pos, team: teamName, team_logo: teamLogo,
                played, wins, draws, losses,
                goals_for: gf, goals_against: ga, goal_diff: gd, points: pts
            });
        }
    }
    return table;
}"""


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
        live_matches = await page.evaluate(LIVE_JS)
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
            logo_el = await page.wait_for_selector("div.al img.Ok", timeout=5000)
            league_logo = await logo_el.get_attribute("src") if logo_el else ""
        except:
            try:
                logo_el = await page.query_selector("img.Ok")
                league_logo = await logo_el.get_attribute("src") if logo_el else ""
            except:
                pass

        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=15000)
            data = await page.evaluate(MATCHES_JS)
            fixtures = data.get("fixtures", [])
            results = data.get("results", [])
        except Exception:
            print(f"⚠️ No matches found for {name}")

        await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('div[data-id^="rw-"]', timeout=15000)
            standings = await page.evaluate(STANDINGS_JS)
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
