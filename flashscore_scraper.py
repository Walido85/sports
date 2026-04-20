import asyncio
import json
import os
import re
from typing import List, Dict

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

# ---------------------------------------------------------------------------
# FIRESTORE
# ---------------------------------------------------------------------------
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("❌ No FIREBASE_CREDENTIALS found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project='tunisia-radios-d7aa8', credentials=credentials, database='walid')
print("✅ Firestore connected → collection 'test'")

# ---------------------------------------------------------------------------
# LEAGUES
# ---------------------------------------------------------------------------
LEAGUES = [
    {
        "key": "tunisia_ligue1",
        "name": "Tunisia Ligue 1",
        "url": "https://www.ysscores.com/en/championship/76040/Tunisian-Professional-League-1",
        "standings_url": "https://www.ysscores.com/en/rank/901568/Tunisian-Professional-League-1",
        "results_url": "https://www.ysscores.com/en/championship/76040/Tunisian-Professional-League-1-statics",
    },
    {
        "key": "tunisia_cup",
        "name": "Tunisia Cup",
        "url": "https://www.ysscores.com/en/championship/533123/Tunisian-Cup",
        "standings_url": None,
        "results_url": "https://www.ysscores.com/en/championship/533123/Tunisian-Cup-statics",
    },
    {
        "key": "premier_league",
        "name": "Premier League",
        "url": "https://www.ysscores.com/en/championship/6811/Premier-League",
        "standings_url": "https://www.ysscores.com/en/championship/6811/Premier-League-rank",
        "results_url": "https://www.ysscores.com/en/championship/6811/Premier-League-statics",
    },
    {
        "key": "serie_a",
        "name": "Serie A",
        "url": "https://www.ysscores.com/en/championship/3734/Serie-A",
        "standings_url": "https://www.ysscores.com/en/championship/3734/Serie-A-rank",
        "results_url": "https://www.ysscores.com/en/championship/3734/Serie-A-statics",
    },
    {
        "key": "ligue_1",
        "name": "Ligue 1",
        "url": "https://www.ysscores.com/en/championship/1933/Ligue-1",
        "standings_url": "https://www.ysscores.com/en/championship/1933/Ligue-1-rank",
        "results_url": "https://www.ysscores.com/en/championship/1933/Ligue-1-statics",
    },
    {
        "key": "bundesliga",
        "name": "Bundesliga",
        "url": "https://www.ysscores.com/en/championship/2606/Bundesliga",
        "standings_url": "https://www.ysscores.com/en/championship/2606/Bundesliga-rank",
        "results_url": "https://www.ysscores.com/en/championship/2606/Bundesliga-statics",
    },
    {
        "key": "uefa_champions_league",
        "name": "UEFA Champions League",
        "url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League",
        "standings_url": "https://www.ysscores.com/en/rank/904988/UEFA-Champions-League",
        "results_url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League-statics",
    },
    {
        "key": "caf_champions_league",
        "name": "CAF Champions League",
        "url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League",
        "standings_url": "https://www.ysscores.com/en/rank/911131/CAF-Champions-League",
        "results_url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League-statics",
    },
]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def classify_status(result_text: str, css_classes: str) -> str:
    t = result_text.strip()
    c = css_classes.lower()
    if "'" in t or "live" in c or "active-match" in c:
        return "live"
    if re.search(r'^\d+\s*-\s*\d+$', t):
        return "result"
    return "fixture"


def parse_score(result_text: str) -> str:
    m = re.search(r'(\d+)\s*-\s*(\d+)', result_text.strip())
    return f"{m.group(1)} - {m.group(2)}" if m else "-- - --"


def parse_time(result_text: str) -> str:
    m = re.search(r'\d{1,2}:\d{2}', result_text)
    return m.group(0) if m else result_text.strip()


def save(doc_id: str, data: dict) -> None:
    db.collection('test').document(doc_id).set(data)


async def extract_live_details(el) -> dict:
    """Extract comprehensive live match details: minute, scorers, cards, possession."""
    details = {
        "minute": "",
        "scorers_home": [],
        "scorers_away": [],
        "cards": [],
        "possession": {},
        "stats": {},
    }
    
    try:
        # Try to get minute from result-wrap
        result_el = await el.query_selector("div.result-wrap")
        if result_el:
            result_text = (await result_el.inner_text()).strip()
            minute_match = re.search(r"(\d+)'", result_text)
            if minute_match:
                details["minute"] = f"{minute_match.group(1)}'"
        
        # Try to find event list (goals/cards)
        event_items = await el.query_selector_all("div.event-item, span.event, div.score-info")
        for event in event_items:
            event_text = (await event.inner_text()).strip()
            
            # Detect yellow card
            if "🟨" in event_text or "yellow" in event_text.lower():
                details["cards"].append({"type": "yellow", "player": event_text})
            # Detect red card
            elif "🟥" in event_text or "red" in event_text.lower():
                details["cards"].append({"type": "red", "player": event_text})
            # Detect goal
            elif "⚽" in event_text or "goal" in event_text.lower() or "gol" in event_text.lower():
                details["scorers_home"].append(event_text) if "home" in event_text.lower() else details["scorers_away"].append(event_text)
        
        # Try to find possession info
        possession_elem = await el.query_selector("div.possession, span.possession")
        if possession_elem:
            poss_text = (await possession_elem.inner_text()).strip()
            poss_match = re.search(r'(\d+).*?-.*?(\d+)', poss_text)
            if poss_match:
                details["possession"] = {
                    "home": f"{poss_match.group(1)}%",
                    "away": f"{poss_match.group(2)}%"
                }
        
        # Try to find match stats
        stats_elem = await el.query_selector("div.match-stats, div.stats-container")
        if stats_elem:
            stat_items = await stats_elem.query_selector_all("div.stat-item, span.stat")
            for stat in stat_items[:6]:  # Limit to 6 main stats
                stat_text = (await stat.inner_text()).strip()
                if stat_text:
                    details["stats"][stat_text] = True
    
    except:
        pass
    
    return details


async def extract_matches(elements, include_live_details=False) -> tuple:
    live_data: List[Dict] = []
    fixtures_data: List[Dict] = []
    results_data: List[Dict] = []

    for el in elements:
        try:
            home = (await el.get_attribute("home_name") or "").strip()
            away = (await el.get_attribute("away_name") or "").strip()
            home_logo = (await el.get_attribute("home_image") or "").strip()
            away_logo = (await el.get_attribute("away_image") or "").strip()

            if not home or not away:
                home_el = await el.query_selector("div.first-team div.team---item b")
                away_el = await el.query_selector("div.second-team div.team---item b")
                home = (await home_el.inner_text()).strip() if home_el else ""
                away = (await away_el.inner_text()).strip() if away_el else ""

            if not home_logo:
                img = await el.query_selector("div.first-team div.team---item div.img img")
                home_logo = (await img.get_attribute("src") or "") if img else ""
            if not away_logo:
                img = await el.query_selector("div.second-team div.team---item div.img img")
                away_logo = (await img.get_attribute("src") or "") if img else ""

            if not home or not away:
                continue

            css_classes = (await el.get_attribute("class") or "")
            match_id    = (await el.get_attribute("match_id") or "").strip()
            href        = (await el.get_attribute("href") or "").strip()

            result_el   = await el.query_selector("div.result-wrap")
            result_text = (await result_el.inner_text()).strip() if result_el else ""

            status = classify_status(result_text, css_classes)
            score  = parse_score(result_text) if status in ("live", "result") else "-- - --"

            if status == "fixture":
                time = parse_time(result_text)
            elif status == "live":
                time = result_text.strip()
            else:
                time = "FT"

            match_dict = {
                "home":       home,
                "away":       away,
                "home_logo":  home_logo,
                "away_logo":  away_logo,
                "score":      score,
                "time":       time,
                "status":     status,
                "match_id":   match_id,
                "url":        href,
            }

            if status == "live" and include_live_details:
                live_details = await extract_live_details(el)
                match_dict.update(live_details)

            if status == "live":
                live_data.append(match_dict)
            elif status == "result":
                results_data.append(match_dict)
            else:
                fixtures_data.append(match_dict)

        except Exception as e:
            print(f"      ⚠️ Skipped match: {e}")
            continue

    return live_data, fixtures_data, results_data


# ---------------------------------------------------------------------------
# LIVE — ALL UNIFIED
# ---------------------------------------------------------------------------
async def scrape_live(page) -> None:
    print("\n🔴 Scraping LIVE → all leagues ...")
    await page.goto(
        "https://www.ysscores.com/en/today_matches",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path="debug/today_matches.png")
    with open("debug/today_matches.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    wrappers = await page.query_selector_all("div.matches-wrapper")
    all_live_matches: List[Dict] = []

    for wrapper in wrappers:
        champ_title = (await wrapper.get_attribute("champ_title") or "").strip()
        
        elements = await wrapper.query_selector_all("a.ajax-match-item")
        live, _, _ = await extract_matches(elements, include_live_details=True)
        
        if live:
            for match in live:
                match["league"] = champ_title
            all_live_matches.extend(live)

    doc_id = "flashscore_live"
    if all_live_matches:
        save(doc_id, {
            "matches":   all_live_matches,
            "count":     len(all_live_matches),
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        print(f"   ✅ {len(all_live_matches):>3} LIVE → {doc_id}")
    else:
        print("   ℹ️  No live matches")


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
async def scrape_fixtures(page, league: dict) -> None:
    doc_name = league["key"]
    print(f"   ⏳ Fixtures → {league['name']} ...")

    await page.goto(league["url"], wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_fixtures.png")
    with open(f"debug/{doc_name}_fixtures.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    elements = await page.query_selector_all("a.ajax-match-item")
    print(f"      Found {len(elements)} elements")

    _, fixtures_data, _ = await extract_matches(elements)

    doc_id = f"flashscore_{doc_name}_fixtures"
    if fixtures_data:
        save(doc_id, {
            "matches":   fixtures_data,
            "count":     len(fixtures_data),
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        print(f"   ✅ {len(fixtures_data):>3} FIXTURES → {doc_id}")
    else:
        print(f"   ℹ️  No fixtures")


# ---------------------------------------------------------------------------
# RESULTS
# ---------------------------------------------------------------------------
async def scrape_results(page, league: dict) -> None:
    doc_name = league["key"]
    results_url = league.get("results_url")
    if not results_url:
        return

    print(f"   ⏳ Results → {league['name']} ...")

    await page.goto(results_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_results.png")
    with open(f"debug/{doc_name}_results.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    elements = await page.query_selector_all("a.ajax-match-item")
    print(f"      Found {len(elements)} elements")

    _, _, results_data = await extract_matches(elements)

    doc_id = f"flashscore_{doc_name}_results"
    if results_data:
        save(doc_id, {
            "matches":   results_data,
            "count":     len(results_data),
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        print(f"   ✅ {len(results_data):>3} RESULTS → {doc_id}")
    else:
        print(f"   ℹ️  No results")


# ---------------------------------------------------------------------------
# STANDINGS
# ---------------------------------------------------------------------------
async def scrape_standings(page, league: dict) -> None:
    standings_url = league.get("standings_url")
    if not standings_url:
        print(f"   ⏭️  No standings for {league['name']}")
        return

    doc_name = league["key"]
    print(f"   ⏳ Standings → {league['name']} ...")

    await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_standings.png")
    with open(f"debug/{doc_name}_standings.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    main_table = await page.query_selector("div#main_table, div.tab-pos-rank, div.rank-group.main")
    
    if main_table:
        rows = await main_table.query_selector_all("div.rank-row:not(.header)")
    else:
        rows = await page.query_selector_all("div.rank-row:not(.header)")
    
    table: List[Dict] = []
    for row in rows:
        try:
            name_div = await row.query_selector("div.rank-col.name div.team-name, div.rank-col.name")
            if name_div:
                text = (await name_div.inner_text()).strip().lower()
                if text == "players" or "player" in text:
                    break

            pos_el = await row.query_selector("div.rank-col.number")
            position = (await pos_el.inner_text()).strip() if pos_el else ""
            if not position or not position.isdigit():
                continue

            name_div = await row.query_selector("div.rank-col.name div.team-name")
            team = ""
            team_logo = ""
            if name_div:
                img = await name_div.query_selector("img")
                if img:
                    team_logo = (await img.get_attribute("src") or "").strip()
                info_div = await name_div.query_selector("div.info")
                team = (await info_div.inner_text()).strip() if info_div else ""
            else:
                name_div = await row.query_selector("div.rank-col.name")
                team = (await name_div.inner_text()).strip() if name_div else ""

            if not team:
                continue

            played_el = await row.query_selector("div.rank-col.played")
            win_el = await row.query_selector("div.rank-col.win")
            equal_el = await row.query_selector("div.rank-col.equal")
            lose_el = await row.query_selector("div.rank-col.lose")
            goals_el = await row.query_selector("div.rank-col.goals")
            diff_el = await row.query_selector("div.rank-col.diff")
            points_el = await row.query_selector("div.rank-col.points")

            played = (await played_el.inner_text()).strip() if played_el else ""
            wins = (await win_el.inner_text()).strip() if win_el else ""
            draws = (await equal_el.inner_text()).strip() if equal_el else ""
            losses = (await lose_el.inner_text()).strip() if lose_el else ""
            goals = (await goals_el.inner_text()).strip() if goals_el else ""
            diff = (await diff_el.inner_text()).strip() if diff_el else ""
            points = (await points_el.inner_text()).strip() if points_el else ""

            table.append({
                "position":  position,
                "team":      team,
                "team_logo": team_logo,
                "played":    played,
                "wins":      wins,
                "draws":     draws,
                "losses":    losses,
                "goals":     goals,
                "diff":      diff,
                "points":    points,
            })

        except Exception as e:
            print(f"      ⚠️ Skipped row: {e}")
            continue

    doc_id = f"flashscore_{doc_name}_standings"
    if table:
        save(doc_id, {
            "table":     table,
            "count":     len(table),
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        print(f"   ✅ {len(table):>3} rows STANDINGS → {doc_id}")
    else:
        print(f"   ⚠️  No standings rows")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
async def main() -> None:
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/133.0.0.0 Safari/537.36"
            ),
            extra_http_headers={"Referer": "https://www.ysscores.com/"},
        )
        page = await context.new_page()

        await scrape_live(page)

        for league in LEAGUES:
            print(f"\n🔄 {league['name']}")
            try:
                await scrape_fixtures(page, league)
                await asyncio.sleep(2)
                await scrape_results(page, league)
                await asyncio.sleep(2)
                await scrape_standings(page, league)
                await asyncio.sleep(2)
            except Exception as e:
                print(f"   ❌ Fatal error on {league['name']}: {e}")
                continue

        await browser.close()

    print("\n🎉 Done — check Firestore 'test' collection")


if __name__ == "__main__":
    asyncio.run(main())
