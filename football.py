import asyncio
import json
import os
import re
from typing import List, Dict
from datetime import datetime, timedelta

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
print("✅ Firestore connected → collection 'football'")

# ---------------------------------------------------------------------------
# LEAGUES
# ---------------------------------------------------------------------------
LEAGUES = [
    {
        "key": "tunisia_ligue1",
        "name": "Tunisia Ligue 1",
        "league_logo": "https://imgs.ysscores.com/championship/48/7731690383928.png",
        "url": "https://www.ysscores.com/en/championship/76040/Tunisian-Professional-League-1",
        "standings_url": "https://www.ysscores.com/en/rank/901568/Tunisian-Professional-League-1",
        "results_url": "https://www.ysscores.com/en/championship/76040/Tunisian-Professional-League-1-statics",
    },
    {
        "key": "tunisia_cup",
        "name": "Tunisia Cup",
        "league_logo": "https://imgs.ysscores.com/championship/48/6601696547585.png",
        "url": "https://www.ysscores.com/en/championship/533123/Tunisian-Cup",
        "standings_url": None,
        "results_url": "https://www.ysscores.com/en/championship/533123/Tunisian-Cup-statics",
    },
    {
        "key": "premier_league",
        "name": "Premier League",
        "league_logo": "https://imgs.ysscores.com/championship/48/3411694791422.png",
        "url": "https://www.ysscores.com/en/championship/6811/Premier-League",
        "standings_url": "https://www.ysscores.com/en/championship/6811/Premier-League-rank",
        "results_url": "https://www.ysscores.com/en/championship/6811/Premier-League-statics",
    },
    {
        "key": "serie_a",
        "name": "Serie A",
        "league_logo": "https://imgs.ysscores.com/championship/48/6281692568873.png",
        "url": "https://www.ysscores.com/en/championship/3734/Serie-A",
        "standings_url": "https://www.ysscores.com/en/championship/3734/Serie-A-rank",
        "results_url": "https://www.ysscores.com/en/championship/3734/Serie-A-statics",
    },
    {
        "key": "ligue_1",
        "name": "Ligue 1",
        "league_logo": "https://imgs.ysscores.com/championship/48/17656566406099.png",
        "url": "https://www.ysscores.com/en/championship/1933/Ligue-1",
        "standings_url": "https://www.ysscores.com/en/championship/1933/Ligue-1-rank",
        "results_url": "https://www.ysscores.com/en/championship/1933/Ligue-1-statics",
    },
    {
        "key": "bundesliga",
        "name": "Bundesliga",
        "league_logo": "https://imgs.ysscores.com/championship/48/17693689565274.png",
        "url": "https://www.ysscores.com/en/championship/2606/Bundesliga",
        "standings_url": "https://www.ysscores.com/en/championship/2606/Bundesliga-rank",
        "results_url": "https://www.ysscores.com/en/championship/2606/Bundesliga-statics",
    },
    {
        "key": "uefa_champions_league",
        "name": "UEFA Champions League",
        "league_logo": "https://imgs.ysscores.com/championship/48/1191723239247.png",
        "url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League",
        "standings_url": "https://www.ysscores.com/en/rank/904988/UEFA-Champions-League",
        "results_url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League-statics",
    },
    {
        "key": "caf_champions_league",
        "name": "CAF Champions League",
        "league_logo": "https://imgs.ysscores.com/championship/48/4661694112676.png",
        "url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League",
        "standings_url": "https://www.ysscores.com/en/rank/911131/CAF-Champions-League",
        "results_url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League-statics",
    },
]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def classify_status(result_text: str, css_classes: str) -> str:
    """Classify match status."""
    t = result_text.strip()
    c = css_classes.lower()
    
    if "'" in t and re.search(r"\d+\s*'", t):
        return "live"
    if "live" in c or "active-match" in c or "live-match" in c:
        return "live"
    if re.search(r"half|second half|first half|minute", t.lower()):
        return "live"
    
    if re.search(r'^\d+\s*-\s*\d+$', t):
        return "result"
    if "ft" in t.lower() or "ended" in t.lower() or "final" in t.lower():
        return "result"
    
    return "fixture"


def parse_score(result_text: str) -> str:
    m = re.search(r'(\d+)\s*-\s*(\d+)', result_text.strip())
    return f"{m.group(1)} - {m.group(2)}" if m else "-- - --"


def parse_time(result_text: str) -> str:
    m = re.search(r'\d{1,2}:\d{2}', result_text)
    return m.group(0) if m else result_text.strip()


def extract_date_from_text(text: str) -> str:
    """Extract date carefully - FIXED VERSION."""
    text_lower = text.lower().strip()
    
    # FIXED: Better date patterns
    patterns = [
        r'\b(mon|tue|wed|thu|fri|sat|sun)\s+(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b',
        r'\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b',
        r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text_lower)
        if match:
            return match.group(0)
    
    if "today" in text_lower:
        return "Today"
    if "tomorrow" in text_lower:
        return "Tomorrow"
    if "yesterday" in text_lower:
        return "Yesterday"
    
    return ""


def save(doc_id: str, data: dict, keep_history: bool = False, retention_days: int = 30) -> None:
    """Save current data. Keep history ONLY for results."""
    data["timestamp"] = datetime.utcnow().isoformat()
    
    db.collection('football').document(doc_id).set(data)
    
    if not keep_history:
        return
    
    timestamp = datetime.utcnow().isoformat()
    history_doc_id = f"{doc_id}_history"
    
    new_entry = {
        "timestamp": timestamp,
        "data": data,
        "count": data.get("count", 0),
    }
    
    history_ref = db.collection('football').document(history_doc_id)
    doc = history_ref.get()
    
    if doc.exists:
        history = doc.get('history') or []
    else:
        history = []
    
    history.append(new_entry)
    
    cutoff_date = datetime.utcnow() - timedelta(days=retention_days)
    history = [
        h for h in history 
        if datetime.fromisoformat(h['timestamp']) > cutoff_date
    ]
    
    history_ref.set({"history": history})


async def extract_live_details(el) -> dict:
    """Extract live match details."""
    details = {
        "minute": "",
        "scorers_home": [],
        "scorers_away": [],
        "cards": [],
        "possession": {},
    }
    
    try:
        result_el = await el.query_selector("div.result-wrap")
        if result_el:
            result_text = (await result_el.inner_text()).strip()
            minute_match = re.search(r"(\d+)'", result_text)
            if minute_match:
                details["minute"] = f"{minute_match.group(1)}'"
        
        event_items = await el.query_selector_all("div.event-item, span.event, div.score-info")
        for event in event_items:
            event_text = (await event.inner_text()).strip()
            
            if "🟨" in event_text or "yellow" in event_text.lower():
                details["cards"].append({"type": "yellow", "player": event_text})
            elif "🟥" in event_text or "red" in event_text.lower():
                details["cards"].append({"type": "red", "player": event_text})
            elif "⚽" in event_text or "goal" in event_text.lower():
                if "home" in event_text.lower():
                    details["scorers_home"].append(event_text)
                else:
                    details["scorers_away"].append(event_text)
        
        possession_elem = await el.query_selector("div.possession, span.possession")
        if possession_elem:
            poss_text = (await possession_elem.inner_text()).strip()
            poss_match = re.search(r'(\d+).*?-.*?(\d+)', poss_text)
            if poss_match:
                details["possession"] = {
                    "home": f"{poss_match.group(1)}%",
                    "away": f"{poss_match.group(2)}%"
                }
    
    except:
        pass
    
    return details


async def extract_matches(elements, league_logo="", include_live_details=False) -> tuple:
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
            all_element_text = (await el.inner_text()).strip()

            date = extract_date_from_text(all_element_text)

            result_text = ""
            
            result_el = await el.query_selector("div.result-wrap")
            if result_el:
                result_text = (await result_el.inner_text()).strip()
            
            if not result_text:
                score_el = await el.query_selector("span.score, div.score, span.result, div.result")
                if score_el:
                    result_text = (await score_el.inner_text()).strip()
            
            if not result_text:
                event_el = await el.query_selector("div.event-info, div.match-info, div.match-score")
                if event_el:
                    result_text = (await event_el.inner_text()).strip()
            
            if not result_text:
                score_match = re.search(r'(\d+)\s*-\s*(\d+)', all_element_text)
                if score_match:
                    result_text = f"{score_match.group(1)} - {score_match.group(2)}"
                
                if not result_text and re.search(r'\d+\s*[\':]', all_element_text):
                    result_text = all_element_text.split('\n')[0]

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
                "league_logo": league_logo,
                "date":       date,
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
# LIVE
# ---------------------------------------------------------------------------
async def scrape_live(page) -> None:
    print("\n🔴 LIVE → all leagues ...")
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
        champ_img = (await wrapper.get_attribute("champ_img") or "").strip()
        
        league_logo = ""
        for league in LEAGUES:
            if league["name"].lower() in champ_title.lower() or champ_title.lower() in league["name"].lower():
                league_logo = league.get("league_logo", "")
                break
        
        if not league_logo:
            league_logo = champ_img
        
        elements = await wrapper.query_selector_all("a.ajax-match-item")
        live, _, _ = await extract_matches(elements, league_logo=league_logo, include_live_details=True)
        
        if live:
            for match in live:
                match["league"] = champ_title
            all_live_matches.extend(live)

    if all_live_matches:
        save("live", {
            "matches":   all_live_matches,
            "count":     len(all_live_matches),
        }, keep_history=False)
        print(f"   ✅ {len(all_live_matches):>3} LIVE")
    else:
        print("   ℹ️  No live matches")


# ---------------------------------------------------------------------------
# FIXTURES
# ---------------------------------------------------------------------------
async def scrape_fixtures(page, league: dict) -> None:
    league_name = league["name"]
    league_logo = league.get("league_logo", "")
    print(f"   ⏳ Fixtures → {league_name} ...")

    await page.goto(league["url"], wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{league_name}_fixtures.png")
    with open(f"debug/{league_name}_fixtures.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    elements = await page.query_selector_all("a.ajax-match-item")
    _, fixtures_data, _ = await extract_matches(elements, league_logo=league_logo)

    if fixtures_data:
        save(f"{league_name}_fixtures", {
            "league": league_name,
            "league_logo": league_logo,
            "matches":   fixtures_data,
            "count":     len(fixtures_data),
        }, keep_history=False)
        print(f"   ✅ {len(fixtures_data):>3} FIXTURES")
    else:
        print(f"   ℹ️  No fixtures")


# ---------------------------------------------------------------------------
# RESULTS (WITH HISTORY)
# ---------------------------------------------------------------------------
async def scrape_results(page, league: dict) -> None:
    league_name = league["name"]
    league_logo = league.get("league_logo", "")
    results_url = league.get("results_url")
    if not results_url:
        return

    print(f"   ⏳ Results → {league_name} ...")

    await page.goto(results_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{league_name}_results.png")
    with open(f"debug/{league_name}_results.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    elements = await page.query_selector_all("a.ajax-match-item")
    _, _, results_data = await extract_matches(elements, league_logo=league_logo)

    if results_data:
        save(f"{league_name}_results", {
            "league": league_name,
            "league_logo": league_logo,
            "matches":   results_data,
            "count":     len(results_data),
        }, keep_history=True)
        print(f"   ✅ {len(results_data):>3} RESULTS")
    else:
        print(f"   ℹ️  No results")


# ---------------------------------------------------------------------------
# STANDINGS - COMPLETELY REWRITTEN
# ---------------------------------------------------------------------------
async def scrape_standings(page, league: dict) -> None:
    standings_url = league.get("standings_url")
    if not standings_url:
        print(f"   ⏭️  No standings")
        return

    league_name = league["name"]
    league_logo = league.get("league_logo", "")
    print(f"   ⏳ Standings → {league_name} ...")

    await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{league_name}_standings.png")
    with open(f"debug/{league_name}_standings.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    # Get ALL rows (don't filter yet)
    all_rows = await page.query_selector_all("div.rank-row")
    
    if not all_rows:
        print(f"   ⚠️  No standings rows")
        return
    
    # DETECT GROUPS - look for actual "Group A", "Group B" text patterns
    group_rows = []
    for row in all_rows:
        row_text = (await row.inner_text()).strip()
        # Match: "Group A", "Group B", etc - but NOT team rows
        if re.match(r'^group\s+[a-z]\s*$', row_text.lower()) and not await row.query_selector("div.rank-col.number"):
            group_rows.append(row)
    
    has_groups = len(group_rows) >= 2
    
    if has_groups:
        print(f"      📊 {len(group_rows)} groups detected")
        groups = []
        current_group = None
        current_teams = []
        
        for row in all_rows:
            row_text = (await row.inner_text()).strip()
            
            # Check if GROUP HEADER
            if re.match(r'^group\s+[a-z]\s*$', row_text.lower()) and not await row.query_selector("div.rank-col.number"):
                # Save previous group
                if current_group and current_teams:
                    groups.append({
                        "group": current_group,
                        "teams": current_teams,
                        "count": len(current_teams)
                    })
                current_group = row_text.strip()
                current_teams = []
                continue
            
            # Skip non-team rows
            if not await row.query_selector("div.rank-col.number"):
                continue
            
            # TEAM ROW - extract data
            pos_el = await row.query_selector("div.rank-col.number")
            position = (await pos_el.inner_text()).strip() if pos_el else ""
            
            if not position.isdigit():
                continue
            
            # Extract team
            name_div = await row.query_selector("div.rank-col.name div.team-name")
            team = ""
            team_logo = ""
            
            if name_div:
                img = await name_div.query_selector("img")
                if img:
                    team_logo = (await img.get_attribute("src") or "").strip()
                info_div = await name_div.query_selector("div.info")
                team = (await info_div.inner_text()).strip() if info_div else ""
            
            if not team:
                name_div = await row.query_selector("div.rank-col.name")
                team = (await name_div.inner_text()).strip() if name_div else ""
            
            if team and current_group:
                played_el = await row.query_selector("div.rank-col.played")
                win_el = await row.query_selector("div.rank-col.win")
                equal_el = await row.query_selector("div.rank-col.equal")
                lose_el = await row.query_selector("div.rank-col.lose")
                goals_el = await row.query_selector("div.rank-col.goals")
                diff_el = await row.query_selector("div.rank-col.diff")
                points_el = await row.query_selector("div.rank-col.points")
                
                current_teams.append({
                    "position":  position,
                    "team":      team,
                    "team_logo": team_logo,
                    "played":    (await played_el.inner_text()).strip() if played_el else "",
                    "wins":      (await win_el.inner_text()).strip() if win_el else "",
                    "draws":     (await equal_el.inner_text()).strip() if equal_el else "",
                    "losses":    (await lose_el.inner_text()).strip() if lose_el else "",
                    "goals":     (await goals_el.inner_text()).strip() if goals_el else "",
                    "diff":      (await diff_el.inner_text()).strip() if diff_el else "",
                    "points":    (await points_el.inner_text()).strip() if points_el else "",
                })
        
        # Save last group
        if current_group and current_teams:
            groups.append({
                "group": current_group,
                "teams": current_teams,
                "count": len(current_teams)
            })
        
        if groups:
            save(f"{league_name}_standings", {
                "league": league_name,
                "league_logo": league_logo,
                "type": "grouped",
                "groups": groups,
                "total_groups": len(groups),
            }, keep_history=False)
            total_teams = sum(g['count'] for g in groups)
            print(f"   ✅ {len(groups)} groups, {total_teams} teams")
    
    else:
        # SINGLE TABLE
        print(f"      📊 Single table (no groups)")
        table = []
        max_teams = 30
        
        for row in all_rows:
            try:
                # Skip header rows
                if await row.query_selector("div.rank-col.header"):
                    continue
                
                # Must have position
                pos_el = await row.query_selector("div.rank-col.number")
                position = (await pos_el.inner_text()).strip() if pos_el else ""
                
                if not position or not position.isdigit():
                    continue
                
                # Extract team
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
                
                if not team or "player" in team.lower():
                    continue
                
                played_el = await row.query_selector("div.rank-col.played")
                win_el = await row.query_selector("div.rank-col.win")
                equal_el = await row.query_selector("div.rank-col.equal")
                lose_el = await row.query_selector("div.rank-col.lose")
                goals_el = await row.query_selector("div.rank-col.goals")
                diff_el = await row.query_selector("div.rank-col.diff")
                points_el = await row.query_selector("div.rank-col.points")
                
                table.append({
                    "position":  position,
                    "team":      team,
                    "team_logo": team_logo,
                    "played":    (await played_el.inner_text()).strip() if played_el else "",
                    "wins":      (await win_el.inner_text()).strip() if win_el else "",
                    "draws":     (await equal_el.inner_text()).strip() if equal_el else "",
                    "losses":    (await lose_el.inner_text()).strip() if lose_el else "",
                    "goals":     (await goals_el.inner_text()).strip() if goals_el else "",
                    "diff":      (await diff_el.inner_text()).strip() if diff_el else "",
                    "points":    (await points_el.inner_text()).strip() if points_el else "",
                })
                
                if len(table) >= max_teams:
                    break
            
            except Exception as e:
                print(f"      ⚠️ Skipped row: {e}")
                continue
        
        if table:
            save(f"{league_name}_standings", {
                "league": league_name,
                "league_logo": league_logo,
                "type": "single",
                "table": table,
                "count": len(table),
            }, keep_history=False)
            print(f"   ✅ {len(table)} teams")
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
                print(f"   ❌ Fatal error: {e}")
                continue

        await browser.close()

    print("\n🎉 Done!")


if __name__ == "__main__":
    asyncio.run(main())
