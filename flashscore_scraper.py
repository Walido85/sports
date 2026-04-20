import asyncio
import json
import os
import re
from typing import List, Dict, Optional

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
# All confirmed IDs from ysscores.com DOM inspection.
# ⚠️  76041 (Ligue 2) and 76042 (Cup) are unverified — check debug HTML
#     after first run and correct IDs if pages return 404.
# ---------------------------------------------------------------------------
LEAGUES = [
    {
        "key": "tunisia_ligue1",
        "name": "Tunisia Ligue 1",
        "url": "https://www.ysscores.com/en/championship/76040/Tunisian-Professional-League-1",
        "standings_url": "https://www.ysscores.com/en/rank/901568/Tunisian-Professional-League-1",
    },
    {
        "key": "tunisia_ligue2",
        "name": "Tunisia Ligue 2",
        "url": "https://www.ysscores.com/en/championship/76041/Tunisian-Professional-League-2",
        "standings_url": "https://www.ysscores.com/en/championship/76041/Tunisian-Professional-League-2-rank",
    },
    {
        "key": "tunisia_cup",
        "name": "Tunisia Cup",
        "url": "https://www.ysscores.com/en/championship/76042/Tunisian-Cup",
        "standings_url": None,
    },
    {
        "key": "premier_league",
        "name": "Premier League",
        "url": "https://www.ysscores.com/en/championship/6811/Premier-League",
        "standings_url": "https://www.ysscores.com/en/championship/6811/Premier-League-rank",
    },
    {
        "key": "uefa_champions_league",
        "name": "UEFA Champions League",
        "url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League",
        "standings_url": "https://www.ysscores.com/en/championship/12048/UEFA-Champions-League-rank",
    },
    {
        "key": "caf_champions_league",
        "name": "CAF Champions League",
        "url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League",
        "standings_url": "https://www.ysscores.com/en/championship/77783/CAF-Champions-League-rank",
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


def save_to_firestore(doc_id: str, data: dict) -> None:
    db.collection('test').document(doc_id).set(data)


# ---------------------------------------------------------------------------
# MATCH SCRAPER
# ---------------------------------------------------------------------------
async def scrape_matches(page, league: dict) -> None:
    doc_name = league["key"]
    print(f"   ⏳ Matches → {league['name']} ...")

    await page.goto(league["url"], wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_matches.png")
    with open(f"debug/{doc_name}_matches.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    elements = await page.query_selector_all("a.ajax-match-item")
    print(f"   Found {len(elements)} match elements")

    live_data: List[Dict] = []
    fixtures_data: List[Dict] = []
    results_data: List[Dict] = []

    for el in elements:
        try:
            home = (await el.get_attribute("home_name") or "").strip()
            away = (await el.get_attribute("away_name") or "").strip()

            if not home or not away:
                home_el = await el.query_selector("div.first-team div.team---item b")
                away_el = await el.query_selector("div.second-team div.team---item b")
                home = (await home_el.inner_text()).strip() if home_el else ""
                away = (await away_el.inner_text()).strip() if away_el else ""

            if not home or not away:
                continue

            css_classes = (await el.get_attribute("class") or "")
            match_id    = (await el.get_attribute("match_id") or "").strip()
            href        = (await el.get_attribute("href") or "").strip()

            result_el   = await el.query_selector("div.result-wrap")
            result_text = (await result_el.inner_text()).strip() if result_el else ""

            status = classify_status(result_text, css_classes)
            score  = parse_score(result_text) if status in ("live", "result") else "-- - --"
            time   = parse_time(result_text)  if status == "fixture" else result_text.strip()

            match_dict = {
                "home":     home,
                "away":     away,
                "score":    score,
                "time":     time,
                "status":   status,
                "match_id": match_id,
                "url":      href,
            }

            if status == "live":
                live_data.append(match_dict)
            elif status == "result":
                results_data.append(match_dict)
            else:
                fixtures_data.append(match_dict)

        except Exception as e:
            print(f"   ⚠️ Skipped match: {e}")
            continue

    for category, data in [
        ("live",     live_data),
        ("fixtures", fixtures_data),
        ("results",  results_data),
    ]:
        doc_id = f"flashscore_{doc_name}_{category}"
        if data:
            save_to_firestore(doc_id, {
                "matches":   data,
                "count":     len(data),
                "timestamp": firestore.SERVER_TIMESTAMP,
            })
            print(f"   ✅ {len(data):>3} {category.upper():8} → {doc_id}")
        else:
            print(f"   ℹ️  No {category} matches")


# ---------------------------------------------------------------------------
# STANDINGS SCRAPER
# ---------------------------------------------------------------------------
async def scrape_standings(page, league: dict) -> None:
    if not league.get("standings_url"):
        print(f"   ⏭️  No standings for {league['name']}")
        return

    doc_name = league["key"]
    print(f"   ⏳ Standings → {league['name']} ...")

    await page.goto(league["standings_url"], wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(6)

    os.makedirs("debug", exist_ok=True)
    await page.screenshot(path=f"debug/{doc_name}_standings.png")
    with open(f"debug/{doc_name}_standings.html", "w", encoding="utf-8") as f:
        f.write(await page.content())

    rows = await page.query_selector_all(
        ".rank-table tr, table.ranking-table tr, .standings-table tr, table tr"
    )

    table: List[Dict] = []
    for row in rows:
        cells = await row.query_selector_all("td")
        if len(cells) < 8:
            continue
        texts = [(await c.inner_text()).strip() for c in cells]
        if not re.match(r'^\d+\.?$', texts[0]):
            continue
        table.append({
            "position": texts[0].rstrip("."),
            "team":     texts[1],
            "played":   texts[2],
            "wins":     texts[3],
            "draws":    texts[4],
            "losses":   texts[5],
            "goals":    texts[6],
            "points":   texts[7],
        })

    doc_id = f"flashscore_{doc_name}_standings"
    if table:
        save_to_firestore(doc_id, {
            "table":     table,
            "count":     len(table),
            "timestamp": firestore.SERVER_TIMESTAMP,
        })
        print(f"   ✅ {len(table):>3} rows STANDINGS → {doc_id}")
    else:
        print(f"   ⚠️  No standings rows — inspect debug/{doc_name}_standings.html")


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

        for league in LEAGUES:
            print(f"\n🔄 {league['name']}")
            try:
                await scrape_matches(page, league)
                await scrape_standings(page, league)
                await asyncio.sleep(3)
            except Exception as e:
                print(f"   ❌ Fatal error on {league['name']}: {e}")
                continue

        await browser.close()

    print("\n🎉 Done — check Firestore 'test' collection")


if __name__ == "__main__":
    asyncio.run(main())
