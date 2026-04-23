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
print("✅ Firestore connected → collection 'default'")

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
        # FIXED: championship id 1933 returns La Liga; correct French Ligue 1 id is 1985
        "league_logo": "https://imgs.ysscores.com/championship/48/9551719862665.png",
        "url": "https://www.ysscores.com/en/championship/1985/Ligue-1",
        "standings_url": "https://www.ysscores.com/en/championship/1985/Ligue-1-rank",
        "results_url": "https://www.ysscores.com/en/championship/1985/Ligue-1-statics",
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
    """
    FIXED: ysscores returns times like '07:30 am' / '12:30 pm'. The previous
    regex \\d{1,2}:\\d{2} extracted only the digits and DROPPED the am/pm suffix,
    so '07:30 pm' (19:30) was rendered as '07:30' — same as '07:30 am'.
    Convert to unambiguous 24-hour HH:MM.
    """
    if not result_text:
        return ""
    text = result_text.strip()
    m = re.search(r'(\d{1,2}):(\d{2})\s*(am|pm|AM|PM)?', text)
    if not m:
        return text
    hour = int(m.group(1))
    minute = int(m.group(2))
    suffix = (m.group(3) or "").lower()
    if suffix == "am":
        if hour == 12:
            hour = 0
    elif suffix == "pm":
        if hour != 12:
            hour += 12
    return f"{hour:02d}:{minute:02d}"


def clean_team_name(raw: str) -> str:
    """
    Strip status badges ('Officially qualified', 'Officially relegated', etc.)
    that get rendered on a new line under the team name.
    """
    if not raw:
        return ""
    # Playwright's inner_text puts block-level children on new lines
    first_line = raw.split("\n")[0].strip()
    return first_line


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


async def extract_live_score_and_minute(el) -> dict:
    """
    FIXED: Live matches on ysscores DO NOT use div.result-wrap.
    Their markup is:
        <div class="first-team-result team-result">0</div>    ← home score
        <div class="active-match-progress">
            <span class="live-match-status">Second Half</span> ← phase label
            <div class="match-inner-progress-wrap" data-minutes="56"> ← minute
        </div>
        <div class="second-team-result team-result">0</div>   ← away score

    Previously extract_live_details only looked at div.result-wrap, so live
    matches came through as score="-- - --", minute="", time="", status="live".
    """
    info = {
        "home_score": "",
        "away_score": "",
        "minute": "",
        "live_status": "",
    }
    try:
        h = await el.query_selector("div.first-team-result")
        a = await el.query_selector("div.second-team-result")
        if h:
            info["home_score"] = (await h.inner_text()).strip()
        if a:
            info["away_score"] = (await a.inner_text()).strip()

        minute_wrap = await el.query_selector("div.match-inner-progress-wrap")
        if minute_wrap:
            mins = (await minute_wrap.get_attribute("data-minutes") or "").strip()
            if mins and mins.isdigit():
                info["minute"] = f"{mins}'"

        status_el = await el.query_selector("span.live-match-status")
        if status_el:
            info["live_status"] = (await status_el.inner_text()).strip()
    except Exception:
        pass

    return info


async def extract_live_details(el) -> dict:
    """Richer live-match payload (score/minute/status + placeholders for
    scorers/cards/possession which aren't present in the list view)."""
    details = {
        "minute": "",
        "live_status": "",
        "scorers_home": [],
        "scorers_away": [],
        "cards": [],
        "possession": {},
    }
    try:
        live = await extract_live_score_and_minute(el)
        details["minute"] = live["minute"]
        details["live_status"] = live["live_status"]
    except Exception:
        pass
    return details


async def get_match_date_map(page) -> dict:
    """
    Walk the DOM in document order and build:
        { match_id: { "date": "Tuesday 21-04-2026", "round": "Round 34 - Return Match" } }

    Dates live in <div class="matches-week-title"><a class="champ-title"><b>Round…</b></a>
    <span class="date">…</span></div> which are SIBLINGS of the <a class="ajax-match-item">
    items — NOT descendants. The previous code's `el.query_selector("span.date")`
    always returned nothing.
    """
    try:
        return await page.evaluate("""
            () => {
                const result = {};
                let currentDate = "";
                let currentRound = "";
                const nodes = document.querySelectorAll(
                    'div.matches-week-title, a.ajax-match-item'
                );
                for (const el of nodes) {
                    if (el.classList.contains('matches-week-title')) {
                        const dateEl = el.querySelector('span.date');
                        const roundEl = el.querySelector('a.champ-title b');
                        currentDate = dateEl ? dateEl.innerText.trim() : "";
                        currentRound = roundEl ? roundEl.innerText.trim() : "";
                    } else {
                        const mid = el.getAttribute('match_id');
                        if (mid) {
                            result[mid] = { date: currentDate, round: currentRound };
                        }
                    }
                }
                return result;
            }
        """)
    except Exception as e:
        print(f"      ⚠️ date map failed: {e}")
        return {}


async def extract_matches(
    elements,
    league_logo: str = "",
    include_live_details: bool = False,
    date_map: dict = None,
    default_date: str = "",
) -> tuple:
    live_data: List[Dict] = []
    fixtures_data: List[Dict] = []
    results_data: List[Dict] = []
    date_map = date_map or {}

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

            # Date + round from the matches-week-title header that precedes this
            # match in the DOM (built in get_match_date_map). Fall back to the
            # caller-provided default_date (e.g. today's date for the live page).
            date = ""
            round_name = ""
            if match_id and match_id in date_map:
                date = date_map[match_id].get("date", "") or ""
                round_name = date_map[match_id].get("round", "") or ""
            if not date:
                date = default_date

            # Read result-wrap (used by fixtures + finished results).
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

            # Live matches don't use result-wrap — read live-specific DOM.
            live_info = None
            is_live_by_class = ("live-match" in css_classes.lower()
                                or "active-match" in css_classes.lower())
            if is_live_by_class:
                live_info = await extract_live_score_and_minute(el)

            status = classify_status(result_text, css_classes)

            # Score
            if status == "live" and live_info and live_info["home_score"] and live_info["away_score"]:
                score = f'{live_info["home_score"]} - {live_info["away_score"]}'
            elif status in ("live", "result"):
                score = parse_score(result_text)
            else:
                score = "-- - --"

            # Time / phase label
            if status == "fixture":
                time = parse_time(result_text)
            elif status == "live":
                if live_info and live_info["minute"]:
                    time = live_info["minute"]            # e.g. "56'"
                elif live_info and live_info["live_status"]:
                    time = live_info["live_status"]       # e.g. "Second Half"
                else:
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
                "round":      round_name,
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

    date_map = await get_match_date_map(page)
    # today_matches has no matches-week-title headers — all matches are today.
    # Use today's date (same format the site uses elsewhere) as a fallback so
    # live matches don't come back with date="".
    today_date = datetime.utcnow().strftime("%A %d-%m-%Y")

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
        live, _, _ = await extract_matches(
            elements,
            league_logo=league_logo,
            include_live_details=True,
            date_map=date_map,
            default_date=today_date,
        )

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

    date_map = await get_match_date_map(page)

    elements = await page.query_selector_all("a.ajax-match-item")
    _, fixtures_data, _ = await extract_matches(
        elements,
        league_logo=league_logo,
        date_map=date_map,
    )

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

    date_map = await get_match_date_map(page)

    elements = await page.query_selector_all("a.ajax-match-item")
    _, _, results_data = await extract_matches(
        elements,
        league_logo=league_logo,
        date_map=date_map,
    )

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
# STANDINGS
# ---------------------------------------------------------------------------
async def _parse_rank_row(row, fallback_position: int = 0) -> dict:
    """Parse a single rank-row into a dict. Returns None if the row is empty/header."""
    # Skip header — site uses two patterns:
    #   1) a child <div class="rank-col header">  (most leagues)
    #   2) the row itself has class "header"      (Tunisia Ligue 1)
    if await row.query_selector("div.rank-col.header"):
        return None
    row_classes = (await row.get_attribute("class") or "").lower()
    if "header" in row_classes.split():
        return None

    # Team name + logo — strip nested status badges ("Officially qualified" etc.)
    team = ""
    team_logo = ""
    name_div = await row.query_selector("div.rank-col.name div.team-name")
    if name_div:
        img = await name_div.query_selector("img")
        if img:
            team_logo = (await img.get_attribute("src") or "").strip()
        info_div = await name_div.query_selector("div.info")
        if info_div:
            team = clean_team_name((await info_div.inner_text()))

    if not team:
        name_div = await row.query_selector("div.rank-col.name")
        if name_div:
            team = clean_team_name((await name_div.inner_text()))

    # Skip empty / placeholder rows ("Leaving the championship" has pos but no team)
    if not team or "player" in team.lower():
        return None

    # Position — the 1st-place team often shows a trophy SVG instead of "1",
    # so the cell's inner_text comes back empty. Fall back to the row's
    # ordinal index within its table (fallback_position starts at 1).
    pos_el = await row.query_selector("div.rank-col.number")
    position = (await pos_el.inner_text()).strip() if pos_el else ""
    if not position or not position.isdigit():
        if fallback_position > 0:
            position = str(fallback_position)
        else:
            return None

    played_el = await row.query_selector("div.rank-col.played")
    win_el    = await row.query_selector("div.rank-col.win")
    equal_el  = await row.query_selector("div.rank-col.equal")
    lose_el   = await row.query_selector("div.rank-col.lose")
    goals_el  = await row.query_selector("div.rank-col.goals")
    diff_el   = await row.query_selector("div.rank-col.diff")
    points_el = await row.query_selector("div.rank-col.points")

    return {
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
    }


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

    # FIXED: process as groups whenever AT LEAST ONE groups-item container exists
    # (CAF CL has 4, UEFA CL has 1 labeled "Group A" = the league phase).
    # Previous threshold of >= 2 caused UEFA CL to fall into the single-table
    # branch where it picked up the "Leaving the championship" ghost rows.
    group_containers = await page.query_selector_all("div.collapse-item-wrap.groups-item")

    if group_containers:
        # GROUPED STANDINGS
        print(f"      📊 {len(group_containers)} group(s) detected")
        groups = []

        for group_container in group_containers:
            try:
                group_name_el = await group_container.query_selector(
                    ".collapse-header .champion-item .title span"
                )
                group_name = (await group_name_el.inner_text()).strip() if group_name_el else "Unknown"

                ranking_table = await group_container.query_selector(".collapse-content .ranking-table")
                if not ranking_table:
                    continue

                rank_rows = await ranking_table.query_selector_all("div.rank-row")
                current_teams = []
                team_idx = 0
                for row in rank_rows:
                    try:
                        team_idx += 1
                        team_dict = await _parse_rank_row(row, fallback_position=team_idx)
                        if team_dict:
                            current_teams.append(team_dict)
                        else:
                            # row was skipped (header / empty) — don't consume an index
                            team_idx -= 1
                    except Exception as e:
                        print(f"      ⚠️ Skipped team: {e}")
                        continue

                if current_teams:
                    groups.append({
                        "group": group_name,
                        "teams": current_teams,
                        "count": len(current_teams),
                    })
            except Exception as e:
                print(f"      ⚠️ Skipped group: {e}")
                continue

        if groups:
            save(f"{league_name}_standings", {
                "league": league_name,
                "league_logo": league_logo,
                "type": "grouped",
                "groups": groups,
                "total_groups": len(groups),
            }, keep_history=False)
            total_teams = sum(g['count'] for g in groups)
            print(f"   ✅ {len(groups)} group(s), {total_teams} teams")
        else:
            print(f"   ⚠️  No groups parsed")

    else:
        # SINGLE TABLE
        # FIXED: scope rows to #standing_rank0 to exclude the home/away duplicate
        # tabs (rank_home, rank_away) AND the players_rank tab (Tunisia Ligue 1).
        # The previous global `div.rank-row` query captured ~60 rows for a 20-team
        # league (all + home + away) and was truncated mid-duplicate by max_teams=30.
        print(f"      📊 Single table")
        all_rows = await page.query_selector_all("#standing_rank0 div.rank-row")

        # Fallback if the site ever drops the id
        if not all_rows:
            all_rows = await page.query_selector_all("div.rank_all div.rank-row")
        if not all_rows:
            all_rows = await page.query_selector_all("div.ranking-table div.rank-row")

        table = []
        team_idx = 0
        for row in all_rows:
            try:
                team_idx += 1
                team_dict = await _parse_rank_row(row, fallback_position=team_idx)
                if team_dict:
                    table.append(team_dict)
                else:
                    team_idx -= 1
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
