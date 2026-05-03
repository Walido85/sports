import asyncio
import json
import os
import re
import sys
from typing import List, Dict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

sys.stdout.reconfigure(line_buffering=True)
os.makedirs("debug", exist_ok=True)

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
        "aliases": ["tunisian professional league", "tunisia ligue 1", "ligue professionnelle 1"],
        "league_logo": "https://imgs.ysscores.com/championship/48/7731690383928.png",
        "url": "https://www.ysscores.com/en/championship/76040/Tunisian-Professional-League-1",
        "standings_url": "https://www.ysscores.com/en/rank/901568/Tunisian-Professional-League-1",
        "results_url": "https://www.ysscores.com/en/championship/76040/Tunisian-Professional-League-1-statics"
    },
    {
        "key": "tunisia_cup",
        "name": "Tunisia Cup",
        "aliases": ["tunisian cup", "tunisia cup", "coupe de tunisie"],
        "league_logo": "https://imgs.ysscores.com/championship/48/6601696547585.png",
        "url": "https://www.ysscores.com/en/championship/533123/Tunisian-Cup",
        "standings_url": None,
        "results_url": "https://www.ysscores.com/en/championship/533123/Tunisian-Cup-statics"
    },
    {
        "key": "premier_league",
        "name": "Premier League",
        "aliases": ["premier league", "english premier league", "epl"],
        "league_logo": "https://imgs.ysscores.com/championship/48/3411694791422.png",
        "url": "https://www.ysscores.com/en/championship/6811/Premier-League",
        "standings_url": "https://www.ysscores.com/en/championship/6811/Premier-League-rank",
        "results_url": "https://www.ysscores.com/en/championship/6811/Premier-League-statics"
    },
    {
        "key": "serie_a",
        "name": "Serie A",
        "aliases": ["serie a", "italian serie a", "serie a tim"],
        "league_logo": "https://imgs.ysscores.com/championship/48/6281692568873.png",
        "url": "https://www.ysscores.com/en/championship/3734/Serie-A",
        "standings_url": "https://www.ysscores.com/en/championship/3734/Serie-A-rank",
        "results_url": "https://www.ysscores.com/en/championship/3734/Serie-A-statics"
    },
    {
        "key": "ligue_1",
        "name": "Ligue 1",
        "aliases": ["ligue 1", "french ligue 1", "ligue 1 mcdonald", "ligue 1 uber", "ligue1"],
        "league_logo": "https://imgs.ysscores.com/championship/48/17656566406099.png",
        "url": "https://www.ysscores.com/en/championship/1933/Ligue-1",
        "standings_url": "https://www.ysscores.com/en/championship/1933/Ligue-1-rank",
        "results_url": "https://www.ysscores.com/en/championship/1933/Ligue-1-statics"
    },
    {
        "key": "bundesliga",
        "name": "Bundesliga",
        "aliases": ["bundesliga", "german bundesliga", "1. bundesliga"],
        "league_logo": "https://imgs.ysscores.com/championship/48/17693689565274.png",
        "url": "https://www.ysscores.com/en/championship/2606/Bundesliga",
        "standings_url": "https://www.ysscores.com/en/championship/2606/Bundesliga-rank",
        "results_url": "https://www.ysscores.com/en/championship/2606/Bundesliga-statics"
    },
    {
        "key": "uefa_champions_league",
        "name": "UEFA Champions League",
        "aliases": ["uefa champions league", "champions league", "ucl"],
        "league_logo": "https://imgs.ysscores.com/championship/48/1191723239247.png",
        "url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League",
        "standings_url": "https://www.ysscores.com/en/rank/904988/UEFA-Champions-League",
        "results_url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League-statics"
    },
    {
        "key": "caf_champions_league",
        "name": "CAF Champions League",
        "aliases": ["caf champions league", "caf cl", "total energies caf"],
        "league_logo": "https://imgs.ysscores.com/championship/48/4661694112676.png",
        "url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League",
        "standings_url": "https://www.ysscores.com/en/rank/911131/CAF-Champions-League",
        "results_url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League-statics"
    }
]

# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def match_league_logo(champ_title: str, fallback_img: str) -> str:
    """Match a scraped championship title to our known league logos using aliases."""
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

def get_utc_iso(date_str: str, time_str: str, server_tz: str) -> str:
    if not date_str or not time_str or time_str == "FT" or "--" in time_str:
        return ""
    try:
        date_part = date_str.split(", ")[-1] if ", " in date_str else date_str
        if not re.match(r'^\d{2}:\d{2}$', time_str):
            return ""
        dt_naive = datetime.strptime(f"{date_part} {time_str}", "%Y-%m-%d %H:%M")
        try:
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo(server_tz))
        except:
            dt_aware = dt_naive.replace(tzinfo=ZoneInfo("America/Denver"))
        return dt_aware.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:
        print(f"Timezone fix error: {e}")
        return ""

def parse_date_from_text(text: str) -> str:
    cleaned = re.sub(r'\d{1,2}:\d{2}\s*(?:am|pm)?', '', text, flags=re.IGNORECASE).strip()
    if "today" in cleaned.lower():
        return datetime.now().strftime("%d-%m-%Y")
    if "tomorrow" in cleaned.lower():
        return (datetime.now() + timedelta(days=1)).strftime("%d-%m-%Y")
    m = re.search(r'\d{1,2}-\d{1,2}-\d{2,4}', cleaned)
    return m.group(0) if m else ""

def save(doc_id: str, data: dict) -> None:
    data["timestamp"] = datetime.utcnow().isoformat()
    db.collection('football').document(doc_id).set(data)
    count_val = data.get("count", data.get("total_groups", 0))
    DEBUG_STATS[doc_id] = count_val
    safe_doc_id = doc_id.replace(" ", "_")
    try:
        with open(f"debug_{safe_doc_id}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except:
        pass

# ---------------------------------------------------------------------------
# SCRAPERS
# ---------------------------------------------------------------------------
async def scrape_live(page) -> None:
    print("\n🔴 LIVE → all leagues ...")
    await page.goto("https://www.ysscores.com/en/today_matches", wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(3)

    wrappers = await page.query_selector_all("div.matches-wrapper")
    all_live_matches = []

    for wrapper in wrappers:
        champ_title = (await wrapper.get_attribute("champ_title") or "").strip()
        champ_img = (await wrapper.get_attribute("champ_img") or "").strip()
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
                cls_attr = await el.get_attribute("class") or ""

                if classify_status(res_text, cls_attr) != "live":
                    continue

                h_score_el = await el.query_selector(".first-team-result")
                a_score_el = await el.query_selector(".second-team-result")
                if h_score_el and a_score_el:
                    score = f"{(await h_score_el.inner_text()).strip()} - {(await a_score_el.inner_text()).strip()}"
                else:
                    score = "-- - --"

                min_el = await el.query_selector(".match-time-status, .live-match-status, .match-inner-progress-wrap .number")
                minute = (await min_el.inner_text()).strip() if min_el else ""

                href = (await el.get_attribute("href") or "").strip()
                if href and not href.startswith("http"):
                    href = "https://www.ysscores.com" + href

                all_live_matches.append({
                    "home": home, "away": away,
                    "home_logo": (await el.get_attribute("home_image") or "").strip(),
                    "away_logo": (await el.get_attribute("away_image") or "").strip(),
                    "league": champ_title, "league_logo": league_logo,
                    "date": standardize_date(datetime.now().strftime("%d-%m-%Y")),
                    "status": "live", "score": score,
                    "minute": minute, "url": href
                })
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
    print(f"   ⏳ Fixtures → {name} ...")

    await page.goto(league["url"], wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(3)

    server_tz = await page.evaluate("""() => {
        let el = document.querySelector('.settings-link-item.timezone .action span');
        return el ? el.innerText.trim() : 'America/Denver';
    }""")

    elements = await page.query_selector_all("div.matches-week-title, a.ajax-match-item")
    curr_date = ""
    fixtures = []

    for el in elements:
        cls_attr = await el.get_attribute("class") or ""
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
                let match = el.innerText.match(/\\d{1,2}:\\d{2}\\s*(?:am|pm|AM|PM)?/i);
                return match ? match[0] : "";
            }""")
            match_time = parse_time_24h(raw_time or res_text)
            match_date = standardize_date(curr_date)

            href = (await el.get_attribute("href") or "").strip()
            if href and not href.startswith("http"):
                href = "https://www.ysscores.com" + href

            fixtures.append({
                "home": home, "away": away,
                "home_logo": (await el.get_attribute("home_image") or "").strip(),
                "away_logo": (await el.get_attribute("away_image") or "").strip(),
                "league_logo": logo,
                "date": match_date, "status": "fixture",
                "time": match_time,
                "timestamp_utc": get_utc_iso(match_date, match_time, server_tz),
                "url": href
            })
        except:
            continue

    if fixtures:
        save(f"{name}_fixtures", {"league": name, "league_logo": logo, "matches": fixtures, "count": len(fixtures)})

async def scrape_results(page, league: dict) -> None:
    name = league["name"]
    logo = league.get("league_logo", "")
    print(f"   ⏳ Results → {name} ...")

    await page.goto(league["results_url"], wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(3)

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
            curr_date = parse_date_from_text((await el.inner_text()).strip())
            continue
        try:
            home = (await el.get_attribute("home_name") or "").strip()
            away = (await el.get_attribute("away_name") or "").strip()
            if not home or not away:
                continue

            res_wrap = await el.query_selector("div.result-wrap")
            res_text = (await res_wrap.inner_text()).strip() if res_wrap else ""
            if classify_status(res_text, cls_attr) != "result":
                continue

            h_s = await el.query_selector("span.first-team-result")
            a_s = await el.query_selector("span.second-team-result")
            score = f"{(await h_s.inner_text()).strip()} - {(await a_s.inner_text()).strip()}" if h_s and a_s else parse_score(res_text)

            match_date = standardize_date(curr_date)
            href = (await el.get_attribute("href") or "").strip()
            if href and not href.startswith("http"):
                href = "https://www.ysscores.com" + href

            results.append({
                "home": home, "away": away,
                "home_logo": (await el.get_attribute("home_image") or "").strip(),
                "away_logo": (await el.get_attribute("away_image") or "").strip(),
                "league_logo": logo,
                "date": match_date, "status": "result",
                "score": score, "time": "FT",
                "timestamp_utc": get_utc_iso(match_date, "12:00", server_tz),
                "url": href
            })
        except:
            continue

    if results:
        save(f"{name}_results", {"league": name, "league_logo": logo, "matches": results, "count": len(results)})

async def scrape_standings(page, league: dict) -> None:
    if not league.get("standings_url"):
        return

    name = league["name"]
    logo = league.get("league_logo", "")
    print(f"   ⏳ Standings → {name} ...")

    await page.goto(league["standings_url"], wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(3)

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
                    groups.append({"group": gn, "teams": teams, "count": len(teams)})
            except:
                continue
        if groups:
            save(f"{name}_standings", {"league": name, "league_logo": logo, "type": "grouped", "groups": groups, "total_groups": len(groups)})
    else:
        rt_el = await page.query_selector("div.ranking-table div.tab-pos-rank.rank_all") or await page.query_selector("div.ranking-table")
        if rt_el:
            rows = await rt_el.query_selector_all("div.rank-row")
            table = await _parse_rank_rows(rows)
            if table:
                save(f"{name}_standings", {"league": name, "league_logo": logo, "type": "single", "table": table, "count": len(table)})

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
            nd = await row.query_selector("div.rank-col.name div.team-name") or await row.query_selector("div.rank-col.name")
            info_el = await nd.query_selector("div.info")
            team = (await info_el.inner_text()).strip() if info_el else (await nd.inner_text()).strip()
            img_el = await nd.query_selector("img")
            t_logo = (await img_el.get_attribute("src") or "").strip() if img_el else ""

            def _get(sel): return row.query_selector(sel)

            table.append({
                "position": pos, "team": team, "team_logo": t_logo,
                "played": (await (await _get("div.rank-col.played")).inner_text()).strip(),
                "wins": (await (await _get("div.rank-col.win")).inner_text()).strip(),
                "draws": (await (await _get("div.rank-col.equal")).inner_text()).strip(),
                "losses": (await (await _get("div.rank-col.lose")).inner_text()).strip(),
                "goals": (await (await _get("div.rank-col.goals")).inner_text()).strip(),
                "diff": (await (await _get("div.rank-col.diff")).inner_text()).strip(),
                "points": (await (await _get("div.rank-col.points")).inner_text()).strip()
            })
        except:
            continue
    return table

async def scrape_league(context, league: dict) -> None:
    page = await context.new_page()
    try:
        print(f"\n🔄 {league['name']}")
        await scrape_fixtures(page, league)
        await scrape_results(page, league)
        await scrape_standings(page, league)
    except Exception as e:
        print(f"   ❌ Error in {league['name']}: {e}")
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
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
        )

        # Live scraping first (single page)
        live_page = await context.new_page()
        await scrape_live(live_page)
        await live_page.close()

        # All leagues run concurrently — each gets its own page
        await asyncio.gather(*[scrape_league(context, league) for league in LEAGUES])

        await browser.close()

    print("\n" + "=" * 40)
    print("📊 FINAL SCRAPE SUMMARY:")
    print("=" * 40)
    for doc, count in DEBUG_STATS.items():
        print(f" {doc.ljust(30)} : {count} items")
    print("=" * 40)
    print("🎉 Done!")

if __name__ == "__main__":
    asyncio.run(main())
