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
    {"name": "Tunisia Ligue 1",      "url": "https://www.livescore.com/en/football/tunisia/ligue-i/"},
    {"name": "Premier League",        "url": "https://www.livescore.com/en/football/england/premier-league/"},
    {"name": "LaLiga",                "url": "https://www.livescore.com/en/football/spain/laliga/"},
    {"name": "Serie A",               "url": "https://www.livescore.com/en/football/italy/serie-a/"},
    {"name": "Bundesliga",            "url": "https://www.livescore.com/en/football/germany/bundesliga/"},
    {"name": "Ligue 1",               "url": "https://www.livescore.com/en/football/france/ligue-1/"},
    {"name": "UEFA Champions League", "url": "https://www.livescore.com/en/football/europe/champions-league/"},
    {"name": "CAF Champions League",  "url": "https://www.livescore.com/en/football/africa/caf-champions-league/"}
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
    function getStats(teamId) {
        const allDivs = document.querySelectorAll('div[data-id^="' + teamId + '_"]');
        let suffix = "";
        for (const d of allDivs) {
            const did = d.getAttribute('data-id');
            if (did.endsWith('_played')) {
                suffix = did.replace(teamId + '_', '').replace('_played', '');
                break;
            }
        }
        if (!suffix) return { played:"0", wins:"0", draws:"0", losses:"0", goals_for:"0", goals_against:"0", goal_diff:"0", points:"0" };
        const g = (stat) => document.querySelector('div[data-id="' + teamId + '_' + suffix + '_' + stat + '"]')?.innerText?.trim() || "0";
        return { played: g('played'), wins: g('wins'), draws: g('draws'), losses: g('losses'), goals_for: g('goalsFor'), goals_against: g('goalsAgainst'), goal_diff: g('goalsDiff'), points: g('points') };
    }

    function parseRow(row) {
        const rowId = row.getAttribute('data-id');
        const teamId = rowId.replace('rw-', '');
        if (!row.querySelector('div[data-id="c-nm"]')) return null;
        const posEl = row.querySelector('div[data-id="c-pos"]');
        const posMatch = (posEl?.innerText?.trim() || "").match(/\\d+/);
        const pos = posMatch ? posMatch[0] : "";
        const teamLink = row.querySelector('div[data-id="c-nm"] a.ux');
        if (!teamLink) return null;
        const teamName = teamLink.innerText?.trim() || "";
        const teamLogo = teamLink.querySelector('div.vx img')?.src || "";
        if (!teamName) return null;
        return { position: pos, team: teamName, team_logo: teamLogo, ...getStats(teamId) };
    }

    // Check for group-stage structure by looking for multiple sub-table containers
    const subTables = document.querySelectorAll('div[data-id^="lt-tb-all-"]');
    if (subTables.length > 1) {
        const groups = [];
        for (const sub of subTables) {
            const subId = sub.getAttribute('data-id');
            // Get group name from tab/header associated with this sub-table
            const tabId = subId.replace('lt-tb-all-', '');
            const tabEl = document.querySelector('div[data-id="lt-tb-all-' + tabId + '-hdr"]') ||
                          document.querySelector('a[id="' + tabId + '__tab"]') ||
                          document.querySelector('div[id="tb-it_' + tabId + '"] a');
            const groupName = tabEl?.innerText?.trim() || subId;
            const rows = sub.querySelectorAll('div[data-id^="rw-"]');
            const table = [];
            for (const row of rows) {
                const entry = parseRow(row);
                if (entry && !table.some(t => t.team === entry.team)) table.push(entry);
            }
            if (table.length > 0) groups.push({ name: groupName, table });
        }
        if (groups.length > 0) return { type: "groups", groups };
    }

    // Standard single table
    const rows = document.querySelectorAll('div[data-id^="rw-"]');
    const table = [];
    for (const row of rows) {
        const entry = parseRow(row);
        if (entry && !table.some(t => t.team === entry.team)) table.push(entry);
    }
    return { type: "single", table };
}"""


async def scrape_all_live(context):
    page = await context.new_page()
    live_matches = []
    try:
        await page.goto("https://www.livescore.com/en/football/live/", wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=10000)
        except:
            pass
        live_matches = await page.evaluate(LIVE_JS)
    except Exception as e:
        print(f"❌ Live: {e}")
    finally:
        await page.close()

    db.collection("football").document("live").set({
        "matches": live_matches,
        "count": len(live_matches),
        "updated_at": datetime.now(timezone.utc).isoformat()
    })
    print(f"✅ live: {len(live_matches)} matches")


async def scrape_league(context, league):
    page = await context.new_page()
    name = league["name"]
    url = league["url"]
    standings_url = url + "standings/"

    fixtures = []
    results = []
    standings = {}
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
            pass

        await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('div[data-id^="rw-"]', timeout=15000)
            standings = await page.evaluate(STANDINGS_JS)
        except Exception:
            pass

        db.collection("football").document(name).set({
            "league": name,
            "league_logo": league_logo,
            "fixtures": fixtures,
            "results": results,
            "standings": standings,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })

        s = standings
        if s.get("type") == "single":
            team_count = len(s.get("table", []))
        else:
            team_count = sum(len(g.get("table", [])) for g in s.get("groups", []))
        print(f"✅ {name}: {len(fixtures)} Fix | {len(results)} Res | {team_count} Teams")

    except Exception as e:
        print(f"❌ {name}: {e}")
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
