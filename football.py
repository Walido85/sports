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
DETAILS_URL = "https://raw.githubusercontent.com/Walido85/sports/data/match_details.json"

MAX_DETAIL_FETCHES_PER_RUN = 20
DETAIL_CONCURRENCY = 5

LEAGUES = [
    {"slug": "tunisia-ligue-1",       "name": "Tunisia Ligue 1",      "url": "https://www.livescore.com/en/football/tunisia/ligue-i/"},
    {"slug": "premier-league",        "name": "Premier League",        "url": "https://www.livescore.com/en/football/england/premier-league/"},
    {"slug": "laliga",                "name": "LaLiga",                "url": "https://www.livescore.com/en/football/spain/laliga/"},
    {"slug": "serie-a",               "name": "Serie A",               "url": "https://www.livescore.com/en/football/italy/serie-a/"},
    {"slug": "bundesliga",            "name": "Bundesliga",            "url": "https://www.livescore.com/en/football/germany/bundesliga/"},
    {"slug": "ligue-1",               "name": "Ligue 1",               "url": "https://www.livescore.com/en/football/france/ligue-1/"},
    {"slug": "uefa-champions-league", "name": "UEFA Champions League", "url": "https://www.livescore.com/en/football/europe/champions-league/"},
    {"slug": "uefa-europa-league",    "name": "UEFA Europa League",    "url": "https://www.livescore.com/en/football/europe/europa-league/"},
    {"slug": "caf-champions-league",  "name": "CAF Champions League",  "url": "https://www.livescore.com/en/football/africa/caf-champions-league/"},
]

# All JS blocks use raw strings (r""") so \n, \d, \s, \b are passed intact to JS.

LIVE_JS = r"""async () => {
    const collected = new Map();
    const collectVisible = () => {
        const rows = document.querySelectorAll('div[data-id*="_mtc-r"]');
        for (const row of rows) {
            const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
            if (!statusText || statusText === "FT" || statusText.includes("Canc") || statusText.includes("Postp") || statusText.includes(":")) continue;

            const homeName = row.querySelector('div[data-id*="hm-tm-nm"]')?.innerText.trim() || "";
            const awayName = row.querySelector('div[data-id*="aw-tm-nm"]')?.innerText.trim() || "";
            if (!homeName || !awayName) continue;

            const linkEl = row.querySelector('a[href*="/football/"]') || row.closest('a[href*="/football/"]');
            const href = linkEl ? linkEl.getAttribute('href') : "";
            const eidMatch = (href || "").match(/\/(\d{5,})\/?$/);
            const dataId = row.getAttribute('data-id') || "";
            const eid = eidMatch ? eidMatch[1] : (dataId.match(/(\d{5,})/)?.[1] || "");

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

            const key = eid || (homeName + "|" + awayName);
            collected.set(key, {
                eid,
                match_url: href ? (href.startsWith("http") ? href : "https://www.livescore.com" + href) : "",
                home: homeName,
                away: awayName,
                home_logo: homeLogo,
                away_logo: awayLogo,
                league: leagueName,
                league_logo: leagueLogo,
                status: "live",
                score: (hScore && aScore) ? (hScore + " - " + aScore) : "-- - --",
                minute: statusText,
                timezone: "UTC"
            });
        }
    };

    collectVisible();
    let lastY = -1;
    for (let step = 0; step < 8; step++) {
        window.scrollBy(0, 850);
        await new Promise(r => setTimeout(r, 180));
        collectVisible();
        const curY = window.scrollY;
        if (curY === lastY) break;
        lastY = curY;
    }
    return Array.from(collected.values());
}"""

MATCHES_JS = r"""async () => {
    const fixMap = new Map();
    const resMap = new Map();

    const collectVisible = () => {
        const rows = document.querySelectorAll('div[data-id*="_mtc-r"]');
        for (const row of rows) {
            const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
            const homeName = row.querySelector('div[data-id*="hm-tm-nm"]')?.innerText.trim() || "";
            const awayName = row.querySelector('div[data-id*="aw-tm-nm"]')?.innerText.trim() || "";
            if (!homeName || !awayName) continue;

            const linkEl = row.querySelector('a[href*="/football/"]') || row.closest('a[href*="/football/"]');
            const href = linkEl ? linkEl.getAttribute('href') : "";
            const eidMatch = (href || "").match(/\/(\d{5,})\/?$/);
            const dataId = row.getAttribute('data-id') || "";
            const eid = eidMatch ? eidMatch[1] : (dataId.match(/(\d{5,})/)?.[1] || "");

            const teamImgs = Array.from(row.querySelectorAll('img')).filter(img => {
                const src = (img.src || "").toLowerCase();
                const alt = (img.alt || "").toLowerCase();
                return src && !src.includes("tv") && !src.includes("broadcaster") && !src.includes("espn") && !alt.includes("espn") && !src.includes("stream");
            });
            const homeLogo = teamImgs[teamImgs.length >= 2 ? teamImgs.length - 2 : 0]?.src || "";
            const awayLogo = teamImgs[teamImgs.length >= 2 ? teamImgs.length - 1 : 1]?.src || "";

            const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.trim() || "";
            const aScore = row.querySelector('div[data-id*="aw-sc"]')?.innerText.trim() || "";

            let matchDate = row.querySelector('span[data-id*="st-dt"]')?.innerText.trim() || row.querySelector('span.jx')?.innerText.trim() || "";
            if (!matchDate) {
                const spans = Array.from(row.querySelectorAll('span'));
                for (const sp of spans) {
                    const t = (sp.innerText || "").trim();
                    if (/^\d{1,2}\s+[A-Za-z]{3}/.test(t) || /^(Today|Yesterday|Tomorrow)$/i.test(t)) {
                        matchDate = t;
                        break;
                    }
                }
            }
            matchDate = matchDate.replace(/\b\d{1,2}:\d{2}\b/g, "").trim();

            const container = row.closest('div[data-index]');
            const stageLabel = container ? (container.querySelector('div[data-id="st-hdr_stg"]')?.innerText.trim() || "") : "";

            const key = eid || (homeName + "|" + awayName + "|" + matchDate);
            const matchObj = {
                eid,
                match_url: href ? (href.startsWith("http") ? href : "https://www.livescore.com" + href) : "",
                home: homeName,
                away: awayName,
                home_logo: homeLogo,
                away_logo: awayLogo,
                date: matchDate,
                round: stageLabel,
                timezone: "UTC"
            };

            if (statusText.includes("FT") || statusText.includes("AET") || statusText.includes("Pen") || statusText.includes("Canc") || statusText.includes("Postp")) {
                matchObj.status = "result";
                matchObj.score = (hScore && aScore) ? (hScore + " - " + aScore) : "-- - --";
                resMap.set(key, matchObj);
            } else if (statusText.includes(":")) {
                matchObj.status = "fixture";
                matchObj.time = statusText;
                fixMap.set(key, matchObj);
            }
        }
    };

    window.scrollTo(0, 0);
    collectVisible();
    let lastY = -1;
    for (let step = 0; step < 6; step++) {
        window.scrollBy(0, 850);
        await new Promise(r => setTimeout(r, 180));
        collectVisible();
        const curY = window.scrollY;
        if (curY === lastY) break;
        lastY = curY;
    }
    return {
        fixtures: Array.from(fixMap.values()),
        results: Array.from(resMap.values())
    };
}"""

STANDINGS_JS = r"""() => {
    function getStats(teamId) {
        const allDivs = document.querySelectorAll('div[data-id^="' + teamId + '_"]');
        let suffix = "";
        for (const d of allDivs) {
            const did = d.getAttribute('data-id') || "";
            if (did.endsWith('_played')) {
                suffix = did.replace(teamId + '_', '').replace('_played', '');
                break;
            }
        }
        if (suffix) {
            const g = (stat) => document.querySelector('div[data-id="' + teamId + '_' + suffix + '_' + stat + '"]')?.innerText?.trim() || "0";
            return {
                played: g('played'),
                wins: g('wins'),
                draws: g('draws'),
                losses: g('losses'),
                goals_for: g('goalsFor'),
                goals_against: g('goalsAgainst'),
                goal_diff: g('goalsDiff'),
                points: g('points')
            };
        }
        return { played:"0", wins:"0", draws:"0", losses:"0", goals_for:"0", goals_against:"0", goal_diff:"0", points:"0" };
    }

    function parseRow(row) {
        const rowId = row.getAttribute('data-id') || "";
        const teamId = rowId.replace('rw-', '');
        const nameCell = row.querySelector('div[data-id="c-nm"]');
        if (!nameCell) return null;

        const posEl = row.querySelector('div[data-id="c-pos"]');
        const posMatch = (posEl?.innerText?.trim() || "").match(/\d+/);
        const pos = posMatch ? posMatch[0] : "";

        const teamLink = nameCell.querySelector('a') || nameCell;
        const teamName = (teamLink.innerText || "").split('\n')[0].trim();
        const teamLogo = nameCell.querySelector('img')?.src || "";
        if (!teamName) return null;

        return { position: pos, team: teamName, team_logo: teamLogo, ...getStats(teamId) };
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
            const rawName = (tabEl?.innerText?.trim() || "").replace(/\s+/g, " ");
            const groupName = (rawName && !rawName.startsWith("#")) ? rawName : "";
            const rows = sub.querySelectorAll('div[data-id^="rw-"]');
            const table = [];
            for (const row of rows) {
                const entry = parseRow(row);
                if (entry && !table.some(t => t.team === entry.team)) table.push(entry);
            }
            if (table.length > 0) groups.push({ name: groupName, table });
        }
        if (groups.length === 1) return { type: "single", table: groups[0].table };
        if (groups.length > 1) return { type: "groups", groups };
    }

    const rows = document.querySelectorAll('div[data-id^="rw-"]');
    const table = [];
    for (const row of rows) {
        const entry = parseRow(row);
        if (entry && !table.some(t => t.team === entry.team)) table.push(entry);
    }
    return { type: "single", table };
}"""

GROUP_LINKS_JS = r"""(basePath) => {
    const urls = [];
    const seen = new Set();
    const links = document.querySelectorAll('a[href]');
    for (const a of links) {
        const href = a.getAttribute('href') || "";
        if (!href.includes(basePath)) continue;
        if (/group-[a-z0-9]/i.test(href) && !href.includes('/standings') && !href.includes('/results')) {
            const full = href.startsWith('http') ? href : ('https://www.livescore.com' + href);
            if (!seen.has(full)) {
                seen.add(full);
                urls.push(full);
            }
        }
    }
    return urls.slice(0, 8);
}"""


def load_json_url(url, label):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TwensaScraper/3.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    print(f"📚 Loaded {label} ({len(data)} entries)")
                    return data
    except Exception:
        print(f"📚 Starting fresh {label}")
    return {}


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def merge_matches(new_items, old_items, max_items=150):
    merged = []
    seen = set()
    for item in (new_items + old_items):
        eid = item.get("eid") or ""
        key = eid if eid else f"{norm(item.get('home'))}|{norm(item.get('away'))}|{item.get('date', '')}|{item.get('score', '')}"
        if key not in seen:
            seen.add(key)
            merged.append(item)
        if len(merged) >= max_items:
            break
    return merged


def parse_esd_to_iso(esd):
    s = str(esd or "").strip()
    if len(s) == 14 and s.isdigit():
        try:
            dt = datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except Exception:
            return ""
    return ""


def parse_scoreboard_payload(sb):
    if not isinstance(sb, dict):
        return {}

    details = {}

    kickoff_iso = parse_esd_to_iso(sb.get("Esd"))
    if kickoff_iso:
        details["kickoff_iso"] = kickoff_iso

    venue_name = sb.get("Vnm") or sb.get("Venue") or ""
    venue_city = sb.get("Vct") or sb.get("City") or ""
    venue_country = sb.get("Vco") or ""
    if venue_name:
        details["stadium"] = {
            "name": str(venue_name).strip(),
            "city": str(venue_city).strip(),
            "country": str(venue_country).strip(),
        }

    refs = sb.get("Refs") or []
    if isinstance(refs, list) and refs:
        first_ref = refs[0]
        if isinstance(first_ref, dict):
            ref_name = first_ref.get("Nm") or first_ref.get("Kn") or ""
            ref_country = first_ref.get("Cn") or ""
            if ref_name:
                details["referee"] = {
                    "name": str(ref_name).strip(),
                    "country": str(ref_country).strip(),
                }
        elif isinstance(first_ref, str) and first_ref.strip():
            details["referee"] = {"name": first_ref.strip(), "country": ""}

    if sb.get("Vsp"):
        details["attendance"] = str(sb.get("Vsp"))

    raw_stats = sb.get("Stat") or []
    if isinstance(raw_stats, list) and len(raw_stats) >= 2:
        h_st = raw_stats[0] if isinstance(raw_stats[0], dict) else {}
        a_st = raw_stats[1] if isinstance(raw_stats[1], dict) else {}
        stat_map = [
            ("possession", "Pss"),
            ("shots_on_target", "Shon"),
            ("shots_off_target", "Shof"),
            ("shots_blocked", "Shbl"),
            ("corners", "Cos"),
            ("offsides", "Ofs"),
            ("fouls", "Fls"),
            ("yellow_cards", "Ycs"),
            ("red_cards", "Rcs"),
            ("saves", "Gks"),
        ]
        parsed_stats = {}
        for label, key in stat_map:
            if key in h_st or key in a_st:
                parsed_stats[label] = {
                    "home": h_st.get(key, 0),
                    "away": a_st.get(key, 0),
                }
        if parsed_stats:
            details["stats"] = parsed_stats

    incs_root = sb.get("Incs") or {}
    events = []
    if isinstance(incs_root, dict):
        for half_key in sorted(incs_root.keys()):
            half_list = incs_root.get(half_key) or []
            if not isinstance(half_list, list):
                continue
            for inc in half_list:
                if not isinstance(inc, dict):
                    continue
                ev_type = {
                    36: "goal",
                    37: "penalty_goal",
                    39: "own_goal",
                    43: "yellow_card",
                    44: "second_yellow",
                    45: "red_card",
                }.get(inc.get("IT"))
                if not ev_type:
                    continue
                minute = str(inc.get("Min", ""))
                if inc.get("MinEx"):
                    minute += f"+{inc.get('MinEx')}"
                team_side = "home" if inc.get("Nm") == 1 else "away"
                player = inc.get("Pn") or ""
                assist = ""
                if isinstance(inc.get("Incs"), list) and inc["Incs"]:
                    assist = inc["Incs"][0].get("Pn") or ""
                events.append({
                    "minute": minute,
                    "type": ev_type,
                    "team": team_side,
                    "player": player,
                    "assist": assist,
                })
    if events:
        details["events"] = events

    lu_root = sb.get("Lu") or []
    if isinstance(lu_root, list) and len(lu_root) >= 2:
        lineups = {}
        for idx, side in enumerate(["home", "away"]):
            lu = lu_root[idx] if isinstance(lu_root[idx], dict) else {}
            formation = "-".join(str(x) for x in lu.get("Fo", [])) if isinstance(lu.get("Fo"), list) else ""
            starters = []
            subs = []
            coach = ""
            for pl in (lu.get("Ps") or []):
                if not isinstance(pl, dict):
                    continue
                p_name = pl.get("Snm") or pl.get("Ln") or ""
                p_num = pl.get("Snu") or ""
                p_pos = pl.get("Pos")
                if p_pos == 1:
                    coach = p_name
                elif pl.get("Pon") == "SUB" or (isinstance(p_pos, int) and p_pos >= 6):
                    subs.append({"name": p_name, "number": p_num})
                else:
                    starters.append({"name": p_name, "number": p_num})
            if formation or starters or coach:
                lineups[side] = {
                    "formation": formation,
                    "coach": coach,
                    "starters": starters[:11],
                    "subs": subs[:12],
                }
        if lineups:
            details["lineups"] = lineups

    return details


async def fetch_match_details(context, match_obj):
    eid = match_obj.get("eid")
    if not eid:
        return {}

    endpoints = [
        f"https://prod-cdn-public-api.livescore.com/v1/api/app/scoreboard/soccer/{eid}?locale=en",
        f"https://prod-cdn-public-api.livescore.com/v1/api/app/statistics/soccer/{eid}?locale=en",
    ]
    merged_raw = {}
    for ep in endpoints:
        try:
            resp = await context.request.get(
                ep,
                headers={
                    "Accept": "application/json",
                    "Origin": "https://www.livescore.com",
                    "Referer": "https://www.livescore.com/",
                },
                timeout=8000,
            )
            if resp.status == 200:
                part = await resp.json()
                if isinstance(part, dict):
                    merged_raw.update(part)
        except Exception:
            continue

    return parse_scoreboard_payload(merged_raw)


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


async def dismiss_cookies(page):
    try:
        btn = await page.query_selector("#onetrust-accept-btn-handler")
        if btn:
            await btn.click()
            await page.wait_for_timeout(300)
    except Exception:
        pass


async def scrape_all_live(context):
    page = await context.new_page()
    live_matches = []
    try:
        await page.goto("https://www.livescore.com/en/football/live/", wait_until="domcontentloaded", timeout=60000)
        await dismiss_cookies(page)
        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=12000)
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
        "updated_at": datetime.now(timezone.utc).isoformat(),
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
        # 1. Main league page (LiveScore's real Fixtures view)
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await dismiss_cookies(page)
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
        except Exception as e:
            print(f"⚠️ {name} fixtures: {e}")

        # 1b. If multi-group cup (e.g. CAF Champions League), also scan Group B/C/D links
        base_path = url.replace("https://www.livescore.com", "")
        try:
            group_urls = await page.evaluate(GROUP_LINKS_JS, base_path)
            for g_url in group_urls:
                if g_url.rstrip("/") == url.rstrip("/"):
                    continue
                try:
                    await page.goto(g_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=6000)
                    g_data = await page.evaluate(MATCHES_JS)
                    fixtures = merge_matches(fixtures, g_data.get("fixtures", []), max_items=100)
                    results = merge_matches(g_data.get("results", []), results, max_items=150)
                except Exception:
                    continue
        except Exception:
            pass

        # 2. Dedicated /results/ page
        try:
            await page.goto(results_url, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=10000)
            res_data = await page.evaluate(MATCHES_JS)
            results = merge_matches(res_data.get("results", []), results, max_items=150)
        except Exception:
            pass

        merged_results = merge_matches(results, old_history.get(slug, []), max_items=150)

        # 3. Dedicated /standings/ page
        await page.goto(standings_url, wait_until="domcontentloaded", timeout=60000)
        try:
            await page.wait_for_selector('div[data-id^="rw-"]', timeout=15000)
            standings = await page.evaluate(STANDINGS_JS)
            standings = attach_form_to_standings(standings, merged_results)
        except Exception as e:
            print(f"⚠️ {name} standings: {e}")

        team_count = (
            len(standings.get("table", []))
            if standings.get("type") == "single"
            else sum(len(g.get("table", [])) for g in standings.get("groups", []))
        )
        print(f"✅ {name}: {len(fixtures)} Fix | {len(merged_results)} Res/Hist | {team_count} Teams")

        return {
            "slug": slug,
            "league": name,
            "league_logo": league_logo,
            "fixtures": fixtures,
            "results": merged_results[:60],
            "standings": standings,
            "updated_at": datetime.now(timezone.utc).isoformat(),
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
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, old_history.get(slug, [])
    finally:
        await page.close()


async def enrich_matches_with_details(context, payload, details_cache):
    to_fetch = []
    seen_eids = set()

    for m in payload.get("live", {}).get("matches", []):
        eid = m.get("eid")
        if eid and eid not in seen_eids:
            seen_eids.add(eid)
            to_fetch.append((m, True))

    for lg in payload.get("leagues", {}).values():
        for m in (lg.get("fixtures") or [])[:4]:
            eid = m.get("eid")
            if eid and eid not in seen_eids:
                seen_eids.add(eid)
                if eid in details_cache and details_cache[eid].get("stadium"):
                    m.update(details_cache[eid])
                else:
                    to_fetch.append((m, False))
        for m in (lg.get("results") or [])[:2]:
            eid = m.get("eid")
            if eid and eid not in seen_eids:
                seen_eids.add(eid)
                if eid in details_cache and details_cache[eid].get("stats"):
                    m.update(details_cache[eid])
                else:
                    to_fetch.append((m, False))

    batch = to_fetch[:MAX_DETAIL_FETCHES_PER_RUN]
    sem = asyncio.Semaphore(DETAIL_CONCURRENCY)

    async def worker(match_obj):
        async with sem:
            info = await fetch_match_details(context, match_obj)
            if info:
                match_obj.update(info)
                eid = match_obj.get("eid")
                if eid:
                    details_cache[eid] = info

    if batch:
        await asyncio.gather(*(worker(m) for m, _ in batch))
        print(f"🔎 Enriched {len(batch)} matches with stadium, referee, stats, events & lineups")

    for lg in payload.get("leagues", {}).values():
        for bucket in ("fixtures", "results"):
            for m in lg.get(bucket, []):
                eid = m.get("eid")
                if eid and eid in details_cache:
                    for k, v in details_cache[eid].items():
                        m.setdefault(k, v)

    if len(details_cache) > 500:
        keys = list(details_cache.keys())[-500:]
        details_cache = {k: details_cache[k] for k in keys}
    return details_cache


async def main():
    old_history = load_json_url(HISTORY_URL, "history")
    details_cache = load_json_url(DETAILS_URL, "match_details")
    new_history = {}
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "live": {},
        "leagues": {},
    }

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            timezone_id="UTC",
            locale="en-GB",
        )
        payload["live"] = await scrape_all_live(context)
        for league in LEAGUES:
            lg_data, lg_hist = await scrape_league(context, league, old_history)
            payload["leagues"][league["slug"]] = lg_data
            new_history[league["slug"]] = lg_hist

        details_cache = await enrich_matches_with_details(context, payload, details_cache)
        await browser.close()

    os.makedirs("public", exist_ok=True)
    with open("public/football.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    with open("public/history.json", "w", encoding="utf-8") as f:
        json.dump(new_history, f, ensure_ascii=False, separators=(",", ":"))
    with open("public/match_details.json", "w", encoding="utf-8") as f:
        json.dump(details_cache, f, ensure_ascii=False, separators=(",", ":"))
    print("💾 Saved public/football.json, public/history.json & public/match_details.json")


if __name__ == "__main__":
    asyncio.run(main())
