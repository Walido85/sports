import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

sys.stdout.reconfigure(line_buffering=True)

HISTORY_URL = "https://raw.githubusercontent.com/Walido85/sports/data/history.json"

LEAGUES = [
    {"slug": "tunisia-ligue-1",       "name": "Tunisia Ligue 1",      "url": "https://www.livescore.com/en/football/tunisia/ligue-i/"},
    {"slug": "premier-league",        "name": "Premier League",        "url": "https://www.livescore.com/en/football/england/premier-league/"},
    {"slug": "laliga",                "name": "LaLiga",                "url": "https://www.livescore.com/en/football/spain/laliga/"},
    {"slug": "serie-a",               "name": "Serie A",               "url": "https://www.livescore.com/en/football/italy/serie-a/"},
    {"slug": "bundesliga",            "name": "Bundesliga",            "url": "https://www.livescore.com/en/football/germany/bundesliga/"},
    {"slug": "ligue-1",               "name": "Ligue 1",               "url": "https://www.livescore.com/en/football/france/ligue-1/"},
    {"slug": "uefa-champions-league", "name": "UEFA Champions League", "url": "https://www.livescore.com/en/football/europe/champions-league/"},
    {"slug": "caf-champions-league",  "name": "CAF Champions League",  "url": "https://www.livescore.com/en/football/africa/caf-champions-league/"}
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

        const teamImgs = Array.from(row.querySelectorAll('img')).filter(img => {
            const src = (img.src || "").toLowerCase();
            const alt = (img.alt || "").toLowerCase();
            return src && !src.includes("tv") && !src.includes("broadcaster") && !src.includes("espn") && !alt.includes("espn") && !src.includes("stream");
        });
        const homeLogo = teamImgs[teamImgs.length >= 2 ? teamImgs.length - 2 : 0]?.src || "";
        const awayLogo = teamImgs[teamImgs.length >= 2 ? teamImgs.length - 1 : 1]?.src || "";

        const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.trim() || "";
        const aScore = row.querySelector('div[data-id*="aw-sc"]')?.innerText.trim() || "";
        const container = row.closest('div[data-index]');
        const leagueName = container ? (container.querySelector('div[data-id="st-hdr_stg"]')?.innerText.trim() || "Other") : "Other";
        const leagueLogo = container ? (container.querySelector('img[src*="stage"], img[src*="flag"], img[src*="competition"], img.Ok')?.src || "") : "";
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

        const teamImgs = Array.from(row.querySelectorAll('img')).filter(img => {
            const src = (img.src || "").toLowerCase();
            const alt = (img.alt || "").toLowerCase();
            return src && !src.includes("tv") && !src.includes("broadcaster") && !src.includes("espn") && !alt.includes("espn") && !src.includes("stream");
        });
        const homeLogo = teamImgs[teamImgs.length >= 2 ? teamImgs.length - 2 : 0]?.src || "";
        const awayLogo = teamImgs[teamImgs.length >= 2 ? teamImgs.length - 1 : 1]?.src || "";

        const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.trim() || "";
        const aScore = row.querySelector('div[data-id*="aw-sc"]')?.innerText.trim() || "";

        // Resilient date extraction (works even if LiveScore changes span.jx)
        let matchDate = row.querySelector('span[data-id*="st-dt"]')?.innerText.trim() || row.querySelector('span.jx')?.innerText.trim() || "";
        if (!matchDate) {
            const spans = Array.from(row.querySelectorAll('span'));
            for (const sp of spans) {
                const t = (sp.innerText || "").trim();
                if (/^\\d{1,2}\\s+[A-Za-z]{3}/.test(t) || /^(Today|Yesterday|Tomorrow)$/i.test(t)) {
                    matchDate = t;
                    break;
                }
            }
        }

        const matchObj = {
            home: homeName, away: awayName,
            home_logo: homeLogo, away_logo: awayLogo,
            date: matchDate, timezone: "UTC"
        };
        if (statusText.includes("FT") || statusText.includes("AET") || statusText.includes("Pen") || statusText.includes("Canc") || statusText.includes("Postp")) {
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
    function getStats(row, teamId) {
        const allDivs = row.querySelectorAll('div[data-id^="' + teamId + '_"]');
        let suffix = "";
        for (const d of allDivs) {
            const did = d.getAttribute('data-id');
            if (did.endsWith('_played')) {
                suffix = did.replace(teamId + '_', '').replace('_played', '');
                break;
            }
        }
        if (suffix) {
            const g = (stat) => row.querySelector('div[data-id="' + teamId + '_' + suffix + '_' + stat + '"]')?.innerText?.trim() || "0";
            return { played: g('played'), wins: g('wins'), draws: g('draws'), losses: g('losses'), goals_for: g('goalsFor'), goals_against: g('goalsAgainst'), goal_diff: g('goalsDiff'), points: g('points') };
        }
        // Fallback: collect numeric cells from row
        const nums = Array.from(row.querySelectorAll('div[data-id], td'))
            .filter(d => {
                const id = d.getAttribute('data-id') || "";
                const txt = (d.innerText || "").trim();
                return id !== "c-pos" && id !== "c-nm" && /^-?\\d+$/.test(txt);
            })
            .map(d => d.innerText.trim());
        if (nums.length >= 8) {
            return { played: nums[0], wins: nums[1], draws: nums[2], losses: nums[3], goals_for: nums[4], goals_against: nums[5], goal_diff: nums[6], points: nums[7] };
        }
        if (nums.length >= 4) {
            return { played: nums[0], wins: "0", draws: "0", losses: "0", goals_for: "0", goals_against: "0", goal_diff: nums[nums.length - 2], points: nums[nums.length - 1] };
        }
        return { played:"0", wins:"0", draws:"0", losses:"0", goals_for:"0", goals_against:"0", goal_diff:"0", points:"0" };
    }

    function parseRow(row) {
        const rowId = row.getAttribute('data-id') || "";
        const teamId = rowId.replace('rw-', '');
        const nameCell = row.querySelector('div[data-id="c-nm"]');
        if (!nameCell) return null;

        const posEl = row.querySelector('div[data-id="c-pos"]');
        const posMatch = (posEl?.innerText?.trim() || "").match(/\\d+/);
        const pos = posMatch ? posMatch[0] : "";

        // Resilient: works without minified classes
        const teamLink = nameCell.querySelector('a') || nameCell;
        const teamName = (teamLink.innerText || "").split('\\n')[0].trim();
        const teamLogo = nameCell.querySelector('img')?.src || "";
        if (!teamName) return null;

        return { position: pos, team: teamName, team_logo: teamLogo, ...getStats(row, teamId) };
    }

    const subTables = document.querySelectorAll('div[data-id^="lt-tb-all-"]');
    if (subTables.length > 1) {
        const groups = [];
        for (const sub of subTables) {
            const subId = sub.getAttribute('data-id');
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

    const rows = document.querySelectorAll('div[data-id^="rw-"]');
    const table = [];
    for (const row of rows) {
        const entry = parseRow(row);
        if (entry && !table.some(t => t.team === entry.team)) table.push(entry);
    }
    return { type: "single", table };
}"""


def load_existing_history():
    try:
        req = urllib.request.Request(HISTORY_URL, headers={"User-Agent": "TwensaScraper/2.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    print(f"📚 Loaded existing history ({len(data)} leagues)")
                    return data
    except Exception:
        print("📚 Starting fresh history archive")
    return {}


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def merge_results(new_items, old_items, max_items=150):
    merged = []
    seen = set()
    for item in (new_items + old_items):
        key = f"{norm(item.get('home'))}|{norm(item.get('away'))}|{item.get('date', '')}|{item.get('score', '')}"
        if key not in seen:
            seen.add(key)
            merged.append(item)
        if len(merged) >= max_items:
            break
    return merged


def attach_form_to_standings(standings, results):
    forms = {}
    for m in results:
        sc = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", m.get("score", ""))
        if not sc:
            continue
        hs, as_ = int(sc.group(1)), int(sc.group(2))
        hk, ak = norm(m.get("home")), norm(m.get("away"))
        forms.setdefault(hk, [])
        forms.setdefault(ak, [])
        if len(forms[hk]) < 5:
            forms[hk].append("W" if hs > as_ else ("L" if hs < as_ else "D"))
        if len(forms[ak]) < 5:
            forms[ak].append("W" if as_ > hs else ("L" if as_ < hs else "D"))

    def enrich(table):
        for row in table:
            row["form"] = forms.get(norm(row.get("team")), [])

    if isinstance(standings, dict):
        if standings.get("type") == "single" and standings.get("table"):
            enrich(standings["table"])
        elif standings.get("type") == "groups" and standings.get("groups"):
            for grp in standings["groups"]:
                if grp.get("table"):
                    enrich(grp["table"])
    return standings


async def scrape_all_live(context):
    page = await context.new_page()
    live_matches = []
    try:
        await page.goto("https://www.livescore.com/en/football/live/", wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=10000)
        except Exception:
            pass
        live_matches = await page.evaluate(LIVE_JS)
    except Exception as e:
        print(f"❌ Live: {e}")
    finally:
        await page.close()

    print(f"✅ live: {len(live_matches)} matches")
    return {
        "matches": live_matches,
        "count": len(live_matches),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }


async def scrape_league(context, league, old_history):
    page = await context.new_page()
    slug = league["slug"]
    name = league["name"]
    url = league["url"]
    results_url = url + "results/"
    standings_url = url + "standings/"

    fixtures = []
    results = []
    standings = {}
    league_logo = ""

    try:
        # 1. Main league page (fixtures + latest results + logo)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            logo_el = await page.wait_for_selector('img[src*="stage"], img[src*="competition"], img.Ok', timeout=5000)
            league_logo = await logo_el.get_attribute("src") if logo_el else ""
        except Exception:
            pass

        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=12000)
            data = await page.evaluate(MATCHES_JS)
            fixtures = data.get("fixtures", [])
            results = data.get("results", [])
        except Exception:
            pass

        # 2. Dedicated /results/ page for deeper results history
        try:
            await page.goto(results_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=10000)
            res_data = await page.evaluate(MATCHES_JS)
            results = merge_results(res_data.get("results", []), results, max_items=150)
        except Exception:
            pass

        # Merge with persistent history archive
        merged_results = merge_results(results, old_history.get(slug, []), max_items=150)

        # 3. Standings page
        await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('div[data-id^="rw-"]', timeout=15000)
            standings = await page.evaluate(STANDINGS_JS)
            standings = attach_form_to_standings(standings, merged_results)
        except Exception:
            pass

        team_count = len(standings.get("table", [])) if standings.get("type") == "single" else sum(len(g.get("table", [])) for g in standings.get("groups", []))
        print(f"✅ {name}: {len(fixtures)} Fix | {len(merged_results)} Res/Hist | {team_count} Teams")

        return {
            "slug": slug,
            "league": name,
            "league_logo": league_logo,
            "fixtures": fixtures,
            "results": merged_results[:60],
            "standings": standings,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, merged_results

    except Exception as e:
        print(f"❌ {name}: {e}")
        return {
            "slug": slug,
            "league": name,
            "league_logo": league_logo,
            "fixtures": fixtures,
            "results": old_history.get(slug, [])[:60],
            "standings": standings,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, old_history.get(slug, [])
    finally:
        await page.close()


async def main():
    old_history = load_existing_history()
    new_history = {}
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "live": {},
        "leagues": {}
    }

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
        payload["live"] = await scrape_all_live(context)
        for league in LEAGUES:
            lg_data, lg_hist = await scrape_league(context, league, old_history)
            payload["leagues"][league["slug"]] = lg_data
            new_history[league["slug"]] = lg_hist
        await browser.close()

    os.makedirs("public", exist_ok=True)
    with open("public/football.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    with open("public/history.json", "w", encoding="utf-8") as f:
        json.dump(new_history, f, ensure_ascii=False, separators=(",", ":"))
    print("💾 Saved public/football.json & public/history.json")


if __name__ == "__main__":
    asyncio.run(main())
