import asyncio
import json
import os
import re
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

# Strict timezone definitions
TUNIS_TZ = ZoneInfo("Africa/Tunis")
UTC_TZ = ZoneInfo("UTC")

sys.stdout.reconfigure(line_buffering=True)

DEBUG_STATS = {}

firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")
if not firebase_secret:
    print("❌ No FIREBASE_CREDENTIALS found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project="tunisia-radios-d7aa8", credentials=credentials, database="(default)")
print("✅ Firestore connected → collection 'football'\n⏳ Scraping in progress. Please wait...")

# ---------------------------------------------------------------------------
# LEAGUES
# ---------------------------------------------------------------------------
LEAGUES = [
    {
        "key": "tunisia_ligue1",
        "name": "Tunisia Ligue 1",
        "aliases": ["tunisian professional league", "tunisia ligue 1", "ligue professionnelle 1", "الرابطة التونسية"],
        "league_logo": "https://imgs.ysscores.com/championship/48/7731690383928.png",
        "url": "https://www.ysscores.com/ar/championship/76040/Tunisian-Professional-League-1",
        "standings_url": "https://www.ysscores.com/ar/rank/901568/Tunisian-Professional-League-1",
        "results_url": "https://www.ysscores.com/ar/championship/76040/Tunisian-Professional-League-1-statics"
    },
    {
        "key": "tunisia_cup",
        "name": "Tunisia Cup",
        "aliases": ["tunisian cup", "tunisia cup", "coupe de tunisie", "كأس تونس"],
        "league_logo": "https://imgs.ysscores.com/championship/48/6601696547585.png",
        "url": "https://www.ysscores.com/ar/championship/533123/Tunisian-Cup",
        "standings_url": None,
        "results_url": "https://www.ysscores.com/ar/championship/533123/Tunisian-Cup-statics"
    },
    {
        "key": "premier_league",
        "name": "Premier League",
        "aliases": ["premier league", "english premier league", "epl", "الدوري الإنجليزي"],
        "league_logo": "https://imgs.ysscores.com/championship/48/3411694791422.png",
        "url": "https://www.ysscores.com/ar/championship/6811/Premier-League",
        "standings_url": "https://www.ysscores.com/ar/championship/6811/Premier-League-rank",
        "results_url": "https://www.ysscores.com/ar/championship/6811/Premier-League-statics"
    },
    {
        "key": "serie_a",
        "name": "Serie A",
        "aliases": ["serie a", "italian serie a", "serie a tim", "الدوري الإيطالي"],
        "league_logo": "https://imgs.ysscores.com/championship/48/6281692568873.png",
        "url": "https://www.ysscores.com/ar/championship/3734/Serie-A",
        "standings_url": "https://www.ysscores.com/ar/championship/3734/Serie-A-rank",
        "results_url": "https://www.ysscores.com/ar/championship/3734/Serie-A-statics"
    },
    {
        "key": "la_liga",
        "name": "La Liga",
        "aliases": ["laliga", "la liga", "spanish la liga", "primera division", "الدوري الإسباني"],
        "league_logo": "https://imgs.ysscores.com/championship/48/17656566406099.png",
        "url": "https://www.ysscores.com/ar/championship/1933/LaLiga",
        "standings_url": "https://www.ysscores.com/ar/championship/1933/LaLiga-rank",
        "results_url": "https://www.ysscores.com/ar/championship/1933/LaLiga-statics"
    },
    {
        "key": "ligue_1",
        "name": "Ligue 1",
        "aliases": ["ligue 1", "french ligue 1", "ligue 1 mcdonald", "الدوري الفرنسي"],
        "league_logo": "https://imgs.ysscores.com/championship/48/4371694791523.png",
        "url": "https://www.ysscores.com/ar/championship/1985/Ligue-1",
        "standings_url": "https://www.ysscores.com/ar/championship/1985/Ligue-1-rank",
        "results_url": "https://www.ysscores.com/ar/championship/1985/Ligue-1-statics"
    },
    {
        "key": "bundesliga",
        "name": "Bundesliga",
        "aliases": ["bundesliga", "german bundesliga", "1. bundesliga", "الدوري الألماني"],
        "league_logo": "https://imgs.ysscores.com/championship/48/17693689565274.png",
        "url": "https://www.ysscores.com/ar/championship/2606/Bundesliga",
        "standings_url": "https://www.ysscores.com/ar/championship/2606/Bundesliga-rank",
        "results_url": "https://www.ysscores.com/ar/championship/2606/Bundesliga-statics"
    },
    {
        "key": "uefa_champions_league",
        "name": "UEFA Champions League",
        "aliases": ["uefa champions league", "champions league", "ucl", "دوري أبطال أوروبا"],
        "league_logo": "https://imgs.ysscores.com/championship/48/1191723239247.png",
        "url": "https://www.ysscores.com/ar/championship/12048/UEFA-Champions-League",
        "standings_url": "https://www.ysscores.com/ar/rank/904988/UEFA-Champions-League",
        "results_url": "https://www.ysscores.com/ar/championship/12048/UEFA-Champions-League-statics"
    },
    {
        "key": "caf_champions_league",
        "name": "CAF Champions League",
        "aliases": ["caf champions league", "caf cl", "دوري أبطال أفريقيا"],
        "league_logo": "https://imgs.ysscores.com/championship/48/4661694112676.png",
        "url": "https://www.ysscores.com/ar/championship/77783/CAF-Champions-League",
        "standings_url": "https://www.ysscores.com/ar/rank/911131/CAF-Champions-League",
        "results_url": "https://www.ysscores.com/ar/championship/77783/CAF-Champions-League-statics"
    }
]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def match_league_logo(champ_title: str, fallback_img: str) -> str:
    t = champ_title.strip().lower()
    for league in LEAGUES:
        for alias in league["aliases"]:
            if alias in t:
                return league["league_logo"]
    return fallback_img

def classify_status(result_text: str, css_classes: str) -> str:
    t = result_text.strip().lower()
    c = css_classes.lower()
    if "live" in c or "active" in c or "progress" in c:
        return "live"
    if "ended" in t or "ft" in t or "نهاية" in t or "انتهت" in t or re.search(r'\d+\s*-\s*\d+', t):
        return "result"
    return "fixture"

def parse_time_24h(raw_text: str) -> str:
    text = raw_text.strip()
    text = text.replace("م", " PM").replace("ص", " AM")
    text = re.sub(r'\s+', ' ', text)
    
    m = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM)?', text, re.IGNORECASE)
    if m:
        hour = int(m.group(1))
        minute = m.group(2)
        ampm = (m.group(3) or "").upper()
        if ampm == "PM" and hour < 12:
            hour += 12
        elif ampm == "AM" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute}"
    m24 = re.search(r'([0-2]?\d):([0-5]\d)', text)
    if m24:
        return f"{int(m24.group(1)):02d}:{m24.group(2)}"
    return text

def standardize_date(date_str: str) -> str:
    if not date_str:
        return ""
    formats = [
        "%A %d-%m-%Y", "%d-%m-%Y", "%d-%b-%Y",
        "%B %d, %Y", "%d %B %Y", "%d %b %Y",
        "%b %d, %Y", "%A %d %B %Y", "%A %d %b %Y"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%A, %Y-%m-%d")
        except ValueError:
            pass
    return date_str

def parse_and_convert_time(date_str: str, time_str: str, server_tz: str) -> tuple[str, str]:
    """Returns (utc_iso_string, tunis_time_string) mathematically correcting the ysscores server timezone"""
    parsed_24h = parse_time_24h(time_str)

    if not date_str or not parsed_24h or parsed_24h == "FT" or "--" in parsed_24h:
        return "", time_str

    try:
        date_part = date_str.split(", ")[-1] if ", " in date_str else date_str
        if not re.match(r'^\d{2}:\d{2}$', parsed_24h):
            return "", time_str

        dt_naive = datetime.strptime(f"{date_part} {parsed_24h}", "%Y-%m-%d %H:%M")

        # Map known ysscores arabic TZ strings to standardized formats if needed
        safe_server_tz = "Europe/Rome"
        if server_tz:
            if "KSA" in server_tz or "السعودية" in server_tz:
                safe_server_tz = "Asia/Riyadh"
            elif "UTC" in server_tz or "العالمي" in server_tz:
                safe_server_tz = "UTC"
            else:
                safe_server_tz = server_tz

        try:
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo(safe_server_tz))
        except Exception:
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo("Europe/Rome"))

        # Convert accurately based on the established aware time
        dt_tunis = dt_aware.astimezone(TUNIS_TZ)
        dt_utc = dt_aware.astimezone(UTC_TZ)

        return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ"), dt_tunis.strftime("%H:%M")
    except Exception:
        return "", time_str

def parse_date_from_text(text: str) -> str:
    cleaned = re.sub(r'\d{1,2}:\d{2}\s*(?:am|pm|ص|م)?', '', text, flags=re.IGNORECASE).strip()
    if "today" in cleaned.lower() or "اليوم" in cleaned:
        return datetime.now(TUNIS_TZ).strftime("%d-%m-%Y")
    if "tomorrow" in cleaned.lower() or "غدا" in cleaned:
        return (datetime.now(TUNIS_TZ) + timedelta(days=1)).strftime("%d-%m-%Y")
    m = re.search(r'\d{1,2}-\d{1,2}-\d{2,4}', cleaned)
    return m.group(0) if m else ""

def save_league(name: str, data: dict) -> None:
    data["updated_at"] = datetime.utcnow().isoformat()
    db.collection("football").document(name).set(data)
    
    fixtures_count = len(data.get("fixtures", []))
    results_count = len(data.get("results", []))
    standings = data.get("standings", {})
    standings_count = len(standings.get("table", standings.get("groups", [])))
    
    DEBUG_STATS[name] = f"fixtures={fixtures_count} results={results_count} standings={standings_count}"

def save_live(matches: list) -> None:
    db.collection("football").document("live").set({
        "matches": matches,
        "count": len(matches),
        "updated_at": datetime.utcnow().isoformat()
    })
    DEBUG_STATS["LIVE"] = f"matches={len(matches)}"

# ---------------------------------------------------------------------------
# MATCH EVENTS 
# ---------------------------------------------------------------------------
async def scrape_match_events(context, match_url: str) -> list:
    events = []
    page = await context.new_page()
    try:
        events_url = match_url.replace("/ar/", "/en/").replace("/fr/", "/en/").replace("/es/", "/en/")
        if not events_url.endswith("-events"):
            events_url = events_url.rstrip("/") + "-events"

        await page.goto(events_url, wait_until="domcontentloaded", timeout=30000)
        
        try:
            await page.wait_for_selector("div.match-event-item", timeout=5000)
        except Exception:
            pass

        event_items = await page.query_selector_all("div.match-event-item")
        for item in event_items:
            try:
                link = await item.query_selector("a.comm_pop")
                if not link:
                    continue

                status_attr = (await link.get_attribute("status") or "").strip()
                player_a     = (await link.get_attribute("player_a") or "").strip()
                player_s     = (await link.get_attribute("player_s") or "").strip()
                player_img   = (await link.get_attribute("player_a_image") or "").strip()
                player_s_img = (await link.get_attribute("player_s_image") or "").strip()
                player_link  = (await link.get_attribute("player_link") or "").strip()
                min_attr     = (await link.get_attribute("min") or "").strip()

                item_classes = (await item.get_attribute("class") or "").lower()
                side = "home" if "for-team-a" in item_classes else "away"

                event_type = {
                    "1": "goal",
                    "2": "yellow_card",
                    "3": "red_card",
                    "4": "substitution"
                }.get(status_attr, "")

                if not event_type:
                    continue

                event = {
                    "type": event_type,
                    "player": player_a,
                    "player_image": player_img,
                    "player_link": player_link,
                    "minute": min_attr,
                    "side": side
                }
                if event_type == "goal":
                    event["assist"] = player_s
                    event["assist_image"] = player_s_img
                elif event_type == "substitution":
                    event["player_out"] = player_s

                events.append(event)
            except Exception:
                continue
    except Exception:
        pass
    finally:
        await page.close()
    return events

# ---------------------------------------------------------------------------
# LIVE SCRAPER
# ---------------------------------------------------------------------------
async def scrape_live(page, context) -> list:
    await page.goto("https://www.ysscores.com/ar/", wait_until="networkidle", timeout=60000)
    
    try:
        await page.wait_for_selector("a.ajax-match-item.live-match, a.ajax-match-item.active-match", timeout=10000)
    except Exception:
        pass

    wrappers = await page.query_selector_all("div.matches-wrapper")
    live_matches_raw = []

    for wrapper in wrappers:
        try:
            champ_title = (await wrapper.get_attribute("champ_title") or "").strip()
            champ_img   = (await wrapper.get_attribute("champ_img") or "").strip()
            league_logo = match_league_logo(champ_title, champ_img)

            elements = await wrapper.query_selector_all("a.ajax-match-item")
            for el in elements:
                try:
                    home = (await el.get_attribute("home_name") or "").strip()
                    away = (await el.get_attribute("away_name") or "").strip()
                    if not home or not away:
                        continue

                    res_wrap = await el.query_selector("div.result-wrap, .active-match-progress")
                    res_text = (await res_wrap.inner_text()).strip() if res_wrap else ""
                    cls_attr = (await el.get_attribute("class") or "")

                    if classify_status(res_text, cls_attr) != "live":
                        continue

                    h_score_el = await el.query_selector(".first-team-result")
                    a_score_el = await el.query_selector(".second-team-result")
                    score = f"{(await h_score_el.inner_text()).strip() if h_score_el else ''} - {(await a_score_el.inner_text()).strip() if a_score_el else ''}"
                    if score == " - ":
                        score = "-- - --"

                    progress_wrap = await el.query_selector(".match-inner-progress-wrap")
                    minute = ""
                    is_halftime = False
                    between_time = ""
                    match_phase = ""

                    if progress_wrap:
                        wrap_cls = (await progress_wrap.get_attribute("class") or "").lower()
                        data_min = (await progress_wrap.get_attribute("data-minutes") or "").strip()
                        
                        phase_el = await progress_wrap.query_selector(".live-match-status")
                        match_phase = (await phase_el.inner_text()).strip() if phase_el else ""

                        if "stopped" in wrap_cls:
                            is_halftime = True
                            minute = "HT"
                            between_el = await el.query_selector(".between-time")
                            if between_el:
                                between_time = (await between_el.inner_text()).strip()
                        else:
                            exact_el = await progress_wrap.query_selector(".percent .number")
                            exact_time = await exact_el.evaluate("el => el.textContent.trim()") if exact_el else ""
                            exact_time = exact_time.replace('\n', '')
                            
                            minute = exact_time if exact_time else (f"{data_min}'" if data_min else "")
                            
                            extra_el = await progress_wrap.query_selector(".extra-count")
                            if extra_el:
                                extra_txt = (await extra_el.inner_text()).strip()
                                if extra_txt and extra_txt not in ["0:0", "00:00", "0", ""]:
                                    minute += f" + {extra_txt}"

                    href = (await el.get_attribute("href") or "").strip()
                    if href and not href.startswith("http"):
                        href = "https://www.ysscores.com" + href

                    live_matches_raw.append({
                        "home": home,
                        "away": away,
                        "home_logo": (await el.get_attribute("home_image") or "").strip(),
                        "away_logo": (await el.get_attribute("away_image") or "").strip(),
                        "league": champ_title,
                        "league_logo": league_logo,
                        "date": standardize_date(datetime.now(TUNIS_TZ).strftime("%d-%m-%Y")),
                        "status": "live",
                        "score": score,
                        "minute": minute,
                        "phase": match_phase,
                        "is_halftime": is_halftime,
                        "between_time": between_time,
                        "url": href
                    })
                except Exception:
                    pass
        except Exception:
            pass

    all_live = []
    if live_matches_raw:
        async def fetch_events(match_data):
            if match_data.get("url"):
                events = await scrape_match_events(context, match_data["url"])
                match_data["events"] = events
            else:
                match_data["events"] = []
            return match_data

        results = await asyncio.gather(*[fetch_events(m) for m in live_matches_raw])
        all_live = list(results)

    save_live(all_live)
    return all_live

# ---------------------------------------------------------------------------
# FIXTURES / RESULTS / STANDINGS
# ---------------------------------------------------------------------------
async def scrape_fixtures(page, league: dict) -> list:
    name = league["name"]
    logo = league.get("league_logo", "")

    await page.goto(league["url"], wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_selector("div.matches-week-title, a.ajax-match-item", timeout=15000)
    except Exception:
        pass

    server_tz = await page.evaluate("""() => {
        let el = document.querySelector('.settings-link-item.timezone .action span');
        return el ? el.innerText.trim() : 'Europe/Rome';
    }""")

    elements = await page.query_selector_all("div.matches-week-title, a.ajax-match-item")
    curr_date = ""
    fixtures = []

    for el in elements:
        cls_attr = (await el.get_attribute("class") or "")
        if "matches-week-title" in cls_attr:
            curr_date = parse_date_from_text((await el.inner_text()).strip())
            continue
        try:
            home = (await el.get_attribute("home_name") or "").strip()
            away = (await el.get_attribute("away_name") or "").strip()
            if not home or not away:
                continue

            res_wrap = await el.query_selector("div.result-wrap")
            res_text = (await res_wrap.inner_text()).strip() if res_wrap else ""
            if classify_status(res_text, cls_attr) != "fixture":
                continue

            raw_time = await el.evaluate("""(el) => {
                let match = el.innerText.match(/\\d{1,2}:\\d{2}\\s*(?:am|pm|AM|PM|ص|م)?/i);
                return match ? match[0] : "";
            }""")
            
            match_date = standardize_date(curr_date)
            # Apply mathematical offset logic to get true Tunis time and UTC
            utc_iso, tunis_time = parse_and_convert_time(match_date, raw_time or res_text, server_tz)

            href = (await el.get_attribute("href") or "").strip()
            if href and not href.startswith("http"):
                href = "https://www.ysscores.com" + href

            fixtures.append({
                "home": home,
                "away": away,
                "home_logo": (await el.get_attribute("home_image") or "").strip(),
                "away_logo": (await el.get_attribute("away_image") or "").strip(),
                "league_logo": logo,
                "date": match_date,
                "status": "fixture",
                "time": tunis_time, 
                "timestamp_utc": utc_iso,
                "url": href
            })
        except Exception:
            pass

    return fixtures


async def scrape_results(page, league: dict) -> list:
    name = league["name"]
    logo = league.get("league_logo", "")

    await page.goto(league["results_url"], wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_selector("div.matches-week-title, a.ajax-match-item", timeout=15000)
    except Exception:
        pass

    server_tz = await page.evaluate("""() => {
        let el = document.querySelector('.settings-link-item.timezone .action span');
        return el ? el.innerText.trim() : 'Europe/Rome';
    }""")

    elements = await page.query_selector_all("div.matches-week-title, a.ajax-match-item")
    curr_date = ""
    results = []

    for el in elements:
        cls_attr = (await el.get_attribute("class") or "")
        if "matches-week-title" in cls_attr:
            curr_date = parse_date_from_text((await el.inner_text()).strip())
            continue
        try:
            home = (await el.get_attribute("home_name") or "").strip()
            away = (await el.get_attribute("away_name") or "").strip()
            if not home or not away:
                continue

            h_s = await el.query_selector("span.first-team-result")
            a_s = await el.query_selector("span.second-team-result")
            if not h_s or not a_s:
                continue

            score = f"{(await h_s.inner_text()).strip()} - {(await a_s.inner_text()).strip()}"
            match_date = standardize_date(curr_date)
            
            utc_iso, _ = parse_and_convert_time(match_date, "12:00 PM", server_tz)

            href = (await el.get_attribute("href") or "").strip()
            if href and not href.startswith("http"):
                href = "https://www.ysscores.com" + href

            results.append({
                "home": home,
                "away": away,
                "home_logo": (await el.get_attribute("home_image") or "").strip(),
                "away_logo": (await el.get_attribute("away_image") or "").strip(),
                "league_logo": logo,
                "date": match_date,
                "status": "result",
                "score": score,
                "time": "FT",
                "timestamp_utc": utc_iso,
                "url": href
            })
        except Exception:
            pass

    return results

async def scrape_standings(page, league: dict) -> dict:
    if not league.get("standings_url"):
        return {}

    await page.goto(league["standings_url"], wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_selector("div.collapse-item-wrap.groups-item, div.ranking-table", timeout=15000)
    except Exception:
        pass

    group_containers = await page.query_selector_all("div.collapse-item-wrap.groups-item")
    if group_containers and len(group_containers) >= 2:
        groups = []
        for gc in group_containers:
            try:
                gn_el = await gc.query_selector(".collapse-header .champion-item .title span")
                gn = (await gn_el.inner_text()).strip() if gn_el else "Unknown"
                rt = await gc.query_selector(".collapse-content .ranking-table")
                if not rt:
                    continue
                rows = await rt.query_selector_all("div.rank-row")
                teams = await _parse_rank_rows(rows)
                if teams:
                    groups.append({"group": gn, "teams": teams})
            except Exception:
                pass
        return {"type": "grouped", "groups": groups} if groups else {}
    else:
        rt_el = (await page.query_selector("div.ranking-table div.tab-pos-rank.rank_all")
                 or await page.query_selector("div.ranking-table"))
        if rt_el:
            rows = await rt_el.query_selector_all("div.rank-row")
            table = await _parse_rank_rows(rows)
            if table:
                return {"type": "single", "table": table}
    return {}

async def _parse_rank_rows(rows) -> list:
    table = []
    for row in rows:
        try:
            if await row.query_selector("div.rank-col.header"):
                continue
            pos_el = await row.query_selector("div.rank-col.number")
            pos = (await pos_el.inner_text()).strip()
            if not pos.isdigit():
                continue
            nd = (await row.query_selector("div.rank-col.name div.team-name")
                  or await row.query_selector("div.rank-col.name"))
            info_el = await nd.query_selector("div.info")
            team = (await info_el.inner_text()).strip() if info_el else (await nd.inner_text()).strip()
            img_el = await nd.query_selector("img")
            t_logo = (await img_el.get_attribute("src") or "").strip() if img_el else ""

            def _get(sel): return row.query_selector(sel)

            table.append({
                "position": pos,
                "team":     team,
                "team_logo": t_logo,
                "played":  (await (await _get("div.rank-col.played")).inner_text()).strip(),
                "wins":    (await (await _get("div.rank-col.win")).inner_text()).strip(),
                "draws":   (await (await _get("div.rank-col.equal")).inner_text()).strip(),
                "losses":  (await (await _get("div.rank-col.lose")).inner_text()).strip(),
                "goals":   (await (await _get("div.rank-col.goals")).inner_text()).strip(),
                "diff":    (await (await _get("div.rank-col.diff")).inner_text()).strip(),
                "points":  (await (await _get("div.rank-col.points")).inner_text()).strip()
            })
        except Exception:
            pass
    return table

# ---------------------------------------------------------------------------
# PER-LEAGUE
# ---------------------------------------------------------------------------
async def scrape_league(context, league: dict) -> None:
    page = await context.new_page()
    try:
        fixtures  = await scrape_fixtures(page, league)
        results   = await scrape_results(page, league)
        standings = await scrape_standings(page, league)

        save_league(league["name"], {
            "league":      league["name"],
            "league_logo": league.get("league_logo", ""),
            "fixtures":    fixtures,
            "results":     results,
            "standings":   standings,
        })
    except Exception:
        pass
    finally:
        await page.close()

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
async def main() -> None:
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        # Enforce Tunis timezone through Playwright Context
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            timezone_id="Africa/Tunis",
            locale="ar-TN"
        )

        live_page = await context.new_page()
        await scrape_live(live_page, context)
        await live_page.close()

        await asyncio.gather(*[scrape_league(context, league) for league in LEAGUES])

        await browser.close()

    print("\n" + "=" * 50)
    print("📊 FINAL SCRAPE SUMMARY:")
    print("=" * 50)
    for doc, info in DEBUG_STATS.items():
        print(f"  {doc.ljust(25)} : {info}")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(main())
