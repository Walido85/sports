import subprocess
import sys

# --- AUTO-INSTALL MISSING DEPENDENCIES ---
# This forces GitHub Actions to download the missing world timezone database!
try:
    import tzdata
except ImportError:
    print("⚙️ Auto-installing missing 'tzdata' package...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "tzdata"])

import asyncio
import json
import os
import re
from typing import List, Dict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

# Force Python to push print statements immediately to GitHub logs
sys.stdout.reconfigure(line_buffering=True)

# Create debug folder for GitHub Artifacts
os.makedirs("debug", exist_ok=True)

# ---------------------------------------------------------------------------
# FIRESTORE & DEBUG TRACKING
# ---------------------------------------------------------------------------
DEBUG_STATS = {}

firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")
if not firebase_secret:
    print("❌ No FIREBASE_CREDENTIALS found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project="tunisia-radios-d7aa8", credentials=credentials, database="(default)")
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
        "results_url": "https://www.ysscores.com/en/championship/76040/Tunisian-Professional-League-1-statics"
    },
    {
        "key": "tunisia_cup", 
        "name": "Tunisia Cup", 
        "league_logo": "https://imgs.ysscores.com/championship/48/6601696547585.png", 
        "url": "https://www.ysscores.com/en/championship/533123/Tunisian-Cup", 
        "standings_url": None, 
        "results_url": "https://www.ysscores.com/en/championship/533123/Tunisian-Cup-statics"
    },
    {
        "key": "premier_league", 
        "name": "Premier League", 
        "league_logo": "https://imgs.ysscores.com/championship/48/3411694791422.png", 
        "url": "https://www.ysscores.com/en/championship/6811/Premier-League", 
        "standings_url": "https://www.ysscores.com/en/championship/6811/Premier-League-rank", 
        "results_url": "https://www.ysscores.com/en/championship/6811/Premier-League-statics"
    },
    {
        "key": "serie_a", 
        "name": "Serie A", 
        "league_logo": "https://imgs.ysscores.com/championship/48/6281692568873.png", 
        "url": "https://www.ysscores.com/en/championship/3734/Serie-A", 
        "standings_url": "https://www.ysscores.com/en/championship/3734/Serie-A-rank", 
        "results_url": "https://www.ysscores.com/en/championship/3734/Serie-A-statics"
    },
    {
        "key": "ligue_1", 
        "name": "Ligue 1", 
        "league_logo": "https://imgs.ysscores.com/championship/48/17656566406099.png", 
        "url": "https://www.ysscores.com/en/championship/1933/Ligue-1", 
        "standings_url": "https://www.ysscores.com/en/championship/1933/Ligue-1-rank", 
        "results_url": "https://www.ysscores.com/en/championship/1933/Ligue-1-statics"
    },
    {
        "key": "bundesliga", 
        "name": "Bundesliga", 
        "league_logo": "https://imgs.ysscores.com/championship/48/17693689565274.png", 
        "url": "https://www.ysscores.com/en/championship/2606/Bundesliga", 
        "standings_url": "https://www.ysscores.com/en/championship/2606/Bundesliga-rank", 
        "results_url": "https://www.ysscores.com/en/championship/2606/Bundesliga-statics"
    },
    {
        "key": "uefa_champions_league", 
        "name": "UEFA Champions League", 
        "league_logo": "https://imgs.ysscores.com/championship/48/1191723239247.png", 
        "url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League", 
        "standings_url": "https://www.ysscores.com/en/rank/904988/UEFA-Champions-League", 
        "results_url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League-statics"
    },
    {
        "key": "caf_champions_league", 
        "name": "CAF Champions League", 
        "league_logo": "https://imgs.ysscores.com/championship/48/4661694112676.png", 
        "url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League", 
        "standings_url": "https://www.ysscores.com/en/rank/911131/CAF-Champions-League", 
        "results_url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League-statics"
    }
]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def append_tz(url: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}time_zone=Africa%2FTunis&time_hour=24"

def classify_status(result_text: str, css_classes: str) -> str:
    t = result_text.strip().lower()
    c = css_classes.lower()
    if "live" in c or "active" in c or "progress" in c:
        return "live"
    if "half" in t or "minute" in t or "'" in t or "live" in t:
        return "live"
    if "ended" in t or "ft" in t or "final" in t or re.search(r'^\d+\s*-\s*\d+$', t):
        return "result"
    return "fixture"

def parse_score(result_text: str) -> str:
    m = re.search(r'(\d+)\s*-\s*(\d+)', result_text.strip())
    if m:
        return f"{m.group(1)} - {m.group(2)}"
    return "-- - --"

def parse_time_24h(raw_text: str) -> str:
    text = raw_text.strip()
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
        h = int(m24.group(1))
        mins = m24.group(2)
        return f"{h:02d}:{mins}"
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
            parsed = datetime.strptime(date_str, fmt)
            return parsed.strftime("%A, %Y-%m-%d")
        except ValueError: 
            pass
    return date_str

def get_utc_iso(date_str: str, time_str: str, server_tz: str) -> str:
    if not date_str or not time_str or time_str == "FT" or "--" in time_str:
        return ""
    try:
        if ", " in date_str:
            date_part = date_str.split(", ")[-1]
        else:
            date_part = date_str
            
        if not re.match(r'^\d{2}:\d{2}$', time_str): 
            return ""
            
        dt_naive = datetime.strptime(f"{date_part} {time_str}", "%Y-%m-%d %H:%M")
        
        try:
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo(server_tz))
        except Exception as e:
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo("America/Denver"))
            
        dt_utc = dt_aware.astimezone(ZoneInfo("UTC"))
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:
        print(f"      ⚠️ Timezone fix error: {e}")
        return ""

def parse_date_from_text(text: str) -> str:
    cleaned = re.sub(r'\d{1,2}:\d{2}\s*(?:am|pm)?', '', text, flags=re.IGNORECASE).strip()
    if "today" in cleaned.lower(): 
        return datetime.now().strftime("%d-%m-%Y")
    if "tomorrow" in cleaned.lower(): 
        return (datetime.now() + timedelta(days=1)).strftime("%d-%m-%Y")
    m = re.search(r'\d{1,2}-\d{1,2}-\d{2,4}', cleaned)
    if m:
        return m.group(0)
    return ""

def save(doc_id: str, data: dict, keep_history: bool = False) -> None:
    data["timestamp"] = datetime.utcnow().isoformat()
            
    db.collection('football').document(doc_id).set(data)
    
    count_val = data.get("count", 0)
    groups_val = data.get("total_groups", 0)
    DEBUG_STATS[doc_id] = count_val if count_val else groups_val
    
    safe_doc_id = doc_id.replace(" ", "_")
    try:
        with open(f"debug_{safe_doc_id}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e: 
        pass
    
    if keep_history:
        history_ref = db.collection('football').document(f"{doc_id}_history")
        doc = history_ref.get()
        if doc.exists:
            history = doc.get('history') or []
        else:
            history = []
        
        hist_entry = {
            "timestamp": data["timestamp"], 
            "data": data, 
            "count": data.get("count", 0)
        }
        history.append(hist_entry)
        history_ref.set({"history": history[-50:]})

async def deep_scrape_match_details(page, match_url: str) -> dict:
    details = {
        "stadium": "", "referee": "", "scorers": [], 
        "cards": [], "possession": {"home": "50%", "away": "50%"}
    }
    if not match_url: 
        return details
    
    new_page = None
    try:
        new_page = await page.context.new_page()
        await new_page.goto(append_tz(match_url), wait_until="networkidle", timeout=30000)
        
        try:
            tabs = await new_page.query_selector_all("ul.nav-tabs li a, .tabs-item, .match-tabs li, .nav-item")
            for tab in tabs:
                text = (await tab.inner_text()).lower()
                if "stat" in text or "event" in text or "timeline" in text or "إحصائيات" in text:
                    await tab.click(timeout=2000)
                    await asyncio.sleep(1) 
        except: 
            pass

        await new_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2) 
        
        smart_data = await new_page.evaluate("""() => {
            let data = { possession: null, minute: null };
            let allElements = Array.from(document.querySelectorAll('span, div, p, b, strong'));
            let minuteEl = allElements.find(el => {
                let t = el.innerText.trim();
                return /^\\d{1,3}'$/.test(t) || /^\\d{1,3}\\+\\d{1,2}'$/.test(t);
            });
            if (minuteEl) {
                data.minute = minuteEl.innerText.trim();
            }
            let rows = document.querySelectorAll('.stat-item, .stat-row, .progress-wrap, div');
            for (let row of rows) {
                let txt = row.innerText.toLowerCase();
                if (txt.includes('possession') || txt.includes('الاستحواذ') || txt.includes('ball')) {
                    let pcts = txt.match(/\\d{1,3}%/g);
                    if (pcts && pcts.length >= 2) {
                        let p1 = parseInt(pcts[0]);
                        let p2 = parseInt(pcts[1]);
                        if (p1 + p2 === 100) {
                            data.possession = { home: pcts[0], away: pcts[1] }; 
                            break;
                        }
                    }
                }
            }
            return data;
        }""")

        if smart_data.get("minute"): 
            details["minute"] = smart_data["minute"]
        if smart_data.get("possession"): 
            details["possession"] = smart_data["possession"]

        h_score_el = await new_page.query_selector(".first-team-result")
        a_score_el = await new_page.query_selector(".second-team-result")
        if h_score_el and a_score_el:
            h_text = (await h_score_el.inner_text()).strip()
            a_text = (await a_score_el.inner_text()).strip()
            details["score"] = f"{h_text} - {a_text}"
            
        if not details.get("minute"):
            min_el = await new_page.query_selector(".match-time-status, .live-minute, .match-time")
            if min_el: 
                details["minute"] = (await min_el.inner_text()).strip()
            
        info_els = await new_page.query_selector_all(".match-info-item")
        for info in info_els:
            text = (await info.inner_text()).strip()
            if "Stadium" in text: 
                details["stadium"] = text.replace("Match Stadium", "").replace("Stadium:", "").strip()
            elif "Referee" in text: 
                details["referee"] = text.replace("Referee:", "").strip()
            
        event_els = await new_page.query_selector_all(".match-event-item, .timeline-item, .event-row")
        for event in event_els:
            try:
                e_time_el = await event.query_selector(".event-time, .time")
                e_player_el = await event.query_selector(".event-player, .player-name")
                if not e_time_el or not e_player_el: 
                    continue
                
                e_time = (await e_time_el.inner_text()).strip()
                e_player = (await e_player_el.inner_text()).strip()
                html = await event.inner_html()
                
                if "icon-yellow-card" in html or "yellow" in html:
                    e_type = "yellow_card"
                elif "icon-red-card" in html or "red" in html:
                    e_type = "red_card"
                else:
                    e_type = "goal"
                    
                cls_attr = await event.get_attribute("class") or ""
                is_home = "home-event" in cls_attr or "right" in cls_attr
                
                event_data = {
                    "time": e_time, 
                    "player": e_player, 
                    "type": e_type, 
                    "side": "home" if is_home else "away"
                }
                
                if e_type == "goal": 
                    details["scorers"].append(event_data)
                else: 
                    details["cards"].append(event_data)
            except: 
                continue
            
    except Exception as e:
        print(f"   ⚠️ Deep scrape warning for {match_url}: {e}")
    finally:
        if new_page:
            try: 
                await new_page.close()
            except: 
                pass
            
    return details

async def scrape_live(page) -> None:
    print("\n🔴 LIVE → all leagues ...")
    
    url = append_tz("https://www.ysscores.com/en/today_matches")
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)
    
    wrappers = await page.query_selector_all("div.matches-wrapper")
    all_live_matches = []
    
    for wrapper in wrappers:
        champ_title = (await wrapper.get_attribute("champ_title") or "").strip()
        champ_img = (await wrapper.get_attribute("champ_img") or "").strip()
        
        league_logo = champ_img
        for l in LEAGUES:
            if l["name"].lower() in champ_title.lower() or champ_title.lower() in l["name"].lower():
                league_logo = l["league_logo"]
                break
                
        elements = await wrapper.query_selector_all("a.ajax-match-item")
        
        for el in elements:
            try:
                home = (await el.get_attribute("home_name") or "").strip()
                away = (await el.get_attribute("away_name") or "").strip()
                if not home or not away: 
                    continue
                
                res_wrap = await el.query_selector("div.result-wrap, .active-match-progress")
                if res_wrap:
                    res_text = (await res_wrap.inner_text()).strip()
                else:
                    res_text = ""
                    
                cls_attr = await el.get_attribute("class") or ""
                if classify_status(res_text, cls_attr) != "live": 
                    continue
                
                home_logo = (await el.get_attribute("home_image") or "").strip()
                away_logo = (await el.get_attribute("away_image") or "").strip()
                
                h_score_el = await el.query_selector(".first-team-result")
                a_score_el = await el.query_selector(".second-team-result")
                if h_score_el and a_score_el:
                    h_val = (await h_score_el.inner_text()).strip()
                    a_val = (await a_score_el.inner_text()).strip()
                    score = f"{h_val} - {a_val}"
                else:
                    score = "-- - --"
                    
                min_el = await el.query_selector(".match-time-status, .live-match-status, .match-inner-progress-wrap .number")
                if min_el:
                    minute = (await min_el.inner_text()).strip()
                else:
                    minute = ""
                
                href = (await el.get_attribute("href") or "").strip()
                if href and not href.startswith("http"): 
                    href = "https://www.ysscores.com" + href
                
                match_dict = {
                    "home": home, "away": away, 
                    "home_logo": home_logo, "away_logo": away_logo, 
                    "league": champ_title, "league_logo": league_logo, 
                    "date": standardize_date(datetime.now().strftime("%d-%m-%Y")), 
                    "status": "live", "score": score, 
                    "minute": minute, "url": href
                }
                
                deep = await deep_scrape_match_details(page, href)
                match_dict.update(deep) 
                all_live_matches.append(match_dict)
            except: 
                continue
                
    if all_live_matches:
        save("live", {"matches": all_live_matches, "count": len(all_live_matches)})
        print(f"   ✅ {len(all_live_matches):>3} LIVE saved")
    else: 
        print("   ℹ️  No live matches")

async def scrape_fixtures(page, league: dict) -> None:
    name = league["name"]
    logo = league.get("league_logo", "")
    url = append_tz(league["url"])
    
    print(f"   ⏳ Fixtures → {name} ...")
    
    await page.goto(url, wait_until="networkidle", timeout=60000)
    await asyncio.sleep(6)
    
    server_tz = await page.evaluate("""() => {
        let el = document.querySelector('.settings-link-item.timezone .action span');
        return el ? el.innerText.trim() : 'America/Denver';
    }""")
    print(f"      🌍 Detected Server Timezone: {server_tz}")
    
    elements = await page.query_selector_all("div.matches-week-title, a.ajax-match-item")
    curr_date = ""
    fixtures = []
    
    for el in elements:
        cls_attr = await el.get_attribute("class") or ""
        if "matches-week-title" in cls_attr:
            txt = (await el.inner_text()).strip()
            curr_date = parse_date_from_text(txt)
            continue
            
        try:
            home = (await el.get_attribute("home_name") or "").strip()
            away = (await el.get_attribute("away_name") or "").strip()
            if not home or not away: 
                continue
            
            res_wrap = await el.query_selector("div.result-wrap")
            if res_wrap:
                res_text = (await res_wrap.inner_text()).strip()
            else:
                res_text = ""
                
            if classify_status(res_text, cls_attr) != "fixture": 
                continue
            
            raw_time = await el.evaluate("""(el) => {
                let match = el.innerText.match(/\\d{1,2}:\\d{2}\\s*(?:am|pm|AM|PM)?/i);
                return match ? match[0] : "";
            }""")
            
            if not raw_time: 
                raw_time = res_text
            
            match_time = parse_time_24h(raw_time)
            match_date = standardize_date(curr_date)
            timestamp_utc = get_utc_iso(match_date, match_time, server_tz)
            
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
                "time": match_time,
                "timestamp_utc": timestamp_utc,
                "url": href
            })
        except: 
            continue
    
    if fixtures: 
        save_data = {
            "league": name, 
            "league_logo": logo, 
            "matches": fixtures, 
            "count": len(fixtures)
        }
        save(f"{name}_fixtures", save_data)

async def scrape_results(page, league: dict) -> None:
    name = league["name"]
    logo = league.get("league_logo", "")
    url = append_tz(league["results_url"])
    
    print(f"   ⏳ Results → {name} ...")
    await page.goto(url, wait_until="networkidle", timeout=60000)
    await asyncio.sleep(6)
    
    server_tz = await page.evaluate("""() => {
        let el = document.querySelector('.settings-link-item.timezone .action span');
        return el ? el.innerText.trim() : 'America/Denver';
    }""")
    
    elements = await page.query_selector_all("div.matches-week-title, a.ajax-match-item")
    curr_date = ""
    results = []
    
    for el in elements:
        cls_attr = await el.get_attribute("class") or ""
        if "matches-week-title" in cls_attr:
            txt = (await el.inner_text()).strip()
            curr_date = parse_date_from_text(txt)
            continue
            
        try:
            home = (await el.get_attribute("home_name") or "").strip()
            away = (await el.get_attribute("away_name") or "").strip()
            if not home or not away: 
                continue
            
            res_wrap = await el.query_selector("div.result-wrap")
            if res_wrap:
                res_text = (await res_wrap.inner_text()).strip()
            else:
                res_text = ""
                
            if classify_status(res_text, cls_attr) != "result": 
                continue
                
            h_s = await el.query_selector("span.first-team-result")
            a_s = await el.query_selector("span.second-team-result")
            
            if h_s and a_s:
                score = f"{(await h_s.inner_text()).strip()} - {(await a_s.inner_text()).strip()}"
            else:
                score = parse_score(res_text)
                
            raw_time = await el.evaluate("""(el) => {
                let match = el.innerText.match(/\\d{1,2}:\\d{2}\\s*(?:am|pm|AM|PM)?/i);
                return match ? match[0] : "";
            }""")
            
            if not raw_time:
                raw_time = "12:00"
                
            match_time = parse_time_24h(raw_time)
            match_date = standardize_date(curr_date)
            timestamp_utc = get_utc_iso(match_date, match_time, server_tz)
            
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
                "timestamp_utc": timestamp_utc,
                "url": href
            })
        except: 
            continue
            
    if results: 
        save_data = {
            "league": name, 
            "league_logo": logo, 
            "matches": results, 
            "count": len(results)
        }
        save(f"{name}_results", save_data, keep_history=True)

async def scrape_standings(page, league: dict) -> None:
    if not league.get("standings_url"): 
        return
        
    name = league["name"]
    logo = league.get("league_logo", "")
    url = append_tz(league["standings_url"])
    
    print(f"   ⏳ Standings → {name} ...")
    
    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)
    
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
                teams = []
                for row in rows:
                    try:
                        if await row.query_selector("div.rank-col.header"): 
                            continue
                        pos_el = await row.query_selector("div.rank-col.number")
                        pos = (await pos_el.inner_text()).strip()
                        if not pos.isdigit(): 
                            continue
                            
                        nd = await row.query_selector("div.rank-col.name div.team-name")
                        info_el = await nd.query_selector("div.info")
                        team = (await info_el.inner_text()).strip()
                        
                        img_el = await nd.query_selector("img")
                        t_logo = (await img_el.get_attribute("src") or "").strip()
                        
                        teams.append({
                            "position": pos, 
                            "team": team, 
                            "team_logo": t_logo,
                            "played": (await (await row.query_selector("div.rank-col.played")).inner_text()).strip(),
                            "wins": (await (await row.query_selector("div.rank-col.win")).inner_text()).strip(),
                            "draws": (await (await row.query_selector("div.rank-col.equal")).inner_text()).strip(),
                            "losses": (await (await row.query_selector("div.rank-col.lose")).inner_text()).strip(),
                            "goals": (await (await row.query_selector("div.rank-col.goals")).inner_text()).strip(),
                            "diff": (await (await row.query_selector("div.rank-col.diff")).inner_text()).strip(),
                            "points": (await (await row.query_selector("div.rank-col.points")).inner_text()).strip()
                        })
                    except: 
                        continue
                if teams: 
                    groups.append({"group": gn, "teams": teams, "count": len(teams)})
            except: 
                continue
                
        if groups: 
            save(f"{name}_standings", {
                "league": name, "league_logo": logo, 
                "type": "grouped", "groups": groups, "total_groups": len(groups)
            })
    else:
        rt_el = await page.query_selector("div.ranking-table div.tab-pos-rank.rank_all")
        if not rt_el: 
            rt_el = await page.query_selector("div.ranking-table") 
            
        if rt_el:
            rows = await rt_el.query_selector_all("div.rank-row")
            table = []
            for row in rows:
                try:
                    if await row.query_selector("div.rank-col.header"): 
                        continue
                    pos_el = await row.query_selector("div.rank-col.number")
                    pos = (await pos_el.inner_text()).strip()
                    if not pos.isdigit(): 
                        continue
                        
                    nd = await row.query_selector("div.rank-col.name div.team-name")
                    if not nd: 
                        nd = await row.query_selector("div.rank-col.name")
                        
                    info_el = await nd.query_selector("div.info")
                    if info_el:
                        team = (await info_el.inner_text()).strip()
                    else:
                        team = (await nd.inner_text()).strip()
                        
                    img_el = await nd.query_selector("img")
                    t_logo = (await img_el.get_attribute("src") or "").strip() if img_el else ""
                    
                    table.append({
                        "position": pos, 
                        "team": team, 
                        "team_logo": t_logo,
                        "played": (await (await row.query_selector("div.rank-col.played")).inner_text()).strip(),
                        "wins": (await (await row.query_selector("div.rank-col.win")).inner_text()).strip(),
                        "draws": (await (await row.query_selector("div.rank-col.equal")).inner_text()).strip(),
                        "losses": (await (await row.query_selector("div.rank-col.lose")).inner_text()).strip(),
                        "goals": (await (await row.query_selector("div.rank-col.goals")).inner_text()).strip(),
                        "diff": (await (await row.query_selector("div.rank-col.diff")).inner_text()).strip(),
                        "points": (await (await row.query_selector("div.rank-col.points")).inner_text()).strip()
                    })
                except: 
                    continue
                    
            if table: 
                save(f"{name}_standings", {
                    "league": name, "league_logo": logo, 
                    "type": "single", "table": table, "count": len(table)
                })

async def main() -> None:
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36", 
            locale="en-GB", 
            timezone_id="Africa/Tunis"
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
                print(f"   ❌ Error: {e}")
            
        await browser.close()
        
    print("\n" + "="*40)
    print("📊 FINAL SCRAPE SUMMARY:")
    print("="*40)
    for doc, count in DEBUG_STATS.items():
        print(f" {doc.ljust(25)} : {count} items saved")
    print("="*40)
    print("🎉 Done!")

if __name__ == "__main__":
    asyncio.run(main())
