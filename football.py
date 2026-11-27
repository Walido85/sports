import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

sys.stdout.reconfigure(line_buffering=True)

HISTORY_URL = "https://raw.githubusercontent.com/Walido85/sports/data/history.json"
DETAILS_URL = "https://raw.githubusercontent.com/Walido85/sports/data/match_details.json"
LIVE_API_URL = "https://prod-cdn-public-api.livescore.com/v1/api/app/live/soccer/0?countryCode=TN&locale=en"
DATE_API_URL = "https://prod-cdn-public-api.livescore.com/v1/api/app/date/soccer/{ymd}/0?countryCode=TN&locale=en"
LOGO_CDN_PREFIX = "https://lsm-static-prod.livescore.com/medium/"

# Fetch past 2 days, today, and next 14 days from LiveScore's public JSON Date API
DATE_WINDOW_PAST_DAYS = 2
DATE_WINDOW_FUTURE_DAYS = 14
API_CONCURRENCY = 6
MAX_DETAIL_FETCHES_PER_RUN = 20

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

API_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.livescore.com",
    "Referer": "https://www.livescore.com/",
}

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


def load_json_url(url, label):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TwensaScraper/5.0"})
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
        eid = str(item.get("eid") or "")
        key = eid if eid else f"{norm(item.get('home'))}|{norm(item.get('away'))}|{item.get('date', '')}|{item.get('score', '')}"
        if key not in seen:
            seen.add(key)
            merged.append(item)
        if len(merged) >= max_items:
            break
    return merged


def parse_esd(esd):
    """Convert LiveScore Esd packed UTC integer (YYYYMMDDHHMMSS) to (iso, 'DD MMM', 'HH:MM')."""
    s = str(esd or "").strip()
    if len(s) == 14 and s.isdigit():
        try:
            dt = datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            return dt.isoformat(), dt.strftime("%d %b").upper(), dt.strftime("%H:%M")
        except Exception:
            pass
    return "", "", ""


def build_logo_url(img_path):
    if not img_path:
        return ""
    s = str(img_path).strip()
    if s.startswith("http"):
        return s
    return LOGO_CDN_PREFIX + s.lstrip("/")


def match_stage_to_slug(st):
    """Map a LiveScore API Stage object (Ccd, Scd, Cnm, CompN, Snm) to one of our 9 league slugs."""
    ccd = (st.get("Ccd") or "").strip().lower()
    scd = (st.get("Scd") or "").strip().lower()
    cnm = (st.get("Cnm") or "").strip().lower()
    comp = (st.get("CompN") or "").strip().lower()
    snm = (st.get("Snm") or "").strip().lower()
    full = f"{ccd} {scd} {cnm} {comp} {snm}"

    if re.search(r"\b(women|woman|feminine|femenina|frauen|u17|u18|u19|u20|u21|u23|youth|reserves?|amateur|futsal)\b", full):
        return ""

    if ccd == "tunisia" and (scd in ("ligue-i", "ligue-1", "ligue-1-pro") or comp in ("ligue i", "ligue 1") or snm.startswith("ligue i")):
        return "tunisia-ligue-1"

    if ccd == "england" and (scd == "premier-league" or comp == "premier league") and "2" not in scd and "cup" not in scd:
        return "premier-league"

    if ccd == "spain" and (scd in ("laliga", "laliga-santander", "primera-division") or comp == "laliga") and "2" not in scd:
        return "laliga"

    if ccd == "italy" and (scd == "serie-a" or comp == "serie a") and "serie-b" not in scd and "serie-c" not in scd:
        return "serie-a"

    if ccd == "germany" and (scd == "bundesliga" or comp == "bundesliga") and "2-bundesliga" not in scd and "2." not in comp and "2." not in snm:
        return "bundesliga"

    if ccd == "france" and (scd == "ligue-1" or comp == "ligue 1") and "ligue-2" not in scd:
        return "ligue-1"

    if ("caf" in full or ccd == "africa") and ("champions-league" in scd or "champions league" in full):
        return "caf-champions-league"

    if ("champions-league" in ccd or "champions-league" in scd or "champions league" in comp or "champions league" in cnm):
        if not any(x in full for x in ("caf", "afc", "concacaf", "ofc", "africa", "asia", "arab", "gulf")):
            return "uefa-champions-league"

    if ("europa-league" in ccd or "europa-league" in scd or "europa league" in comp or "europa league" in cnm):
        if "conference" not in full:
            return "uefa-europa-league"

    return ""


def parse_event_item(ev, st):
    """Normalize a single LiveScore API Event into (bucket, match_dict)."""
    t1_list = ev.get("T1") or []
    t2_list = ev.get("T2") or []
    if not t1_list or not t2_list:
        return None, None
    t1 = t1_list[0] if isinstance(t1_list[0], dict) else {}
    t2 = t2_list[0] if isinstance(t2_list[0], dict) else {}
    home = (t1.get("Nm") or "").strip()
    away = (t2.get("Nm") or "").strip()
    if not home or not away:
        return None, None

    eid = str(ev.get("Eid") or "")
    iso_str, date_lbl, time_lbl = parse_esd(ev.get("Esd"))
    epr = ev.get("Epr")
    esid = ev.get("Esid")
    eps = str(ev.get("Eps") or "").strip()
    tr1 = ev.get("Tr1")
    tr2 = ev.get("Tr2")
    has_score = (tr1 is not None and tr2 is not None and str(tr1) != "" and str(tr2) != "")
    score_str = f"{tr1} - {tr2}" if has_score else "-- - --"

    stage_name = st.get("CompN") or st.get("Snm") or st.get("Cnm") or "Other"
    round_name = st.get("Snm") or ""
    st_logo = build_logo_url(st.get("BadgeUrl") or st.get("Img") or "")

    base = {
        "eid": eid,
        "home": home,
        "away": away,
        "home_logo": build_logo_url(t1.get("Img")),
        "away_logo": build_logo_url(t2.get("Img")),
        "date": date_lbl,
        "kickoff_iso": iso_str,
        "round": round_name,
        "timezone": "UTC",
    }

    is_finished = (epr == 2) or (esid in (6, 13)) or (eps in ("FT", "AET", "AP", "Canc.", "Postp."))
    is_live = (not is_finished) and ((epr == 1) or (esid in (2, 3, 4, 5, 10, 11, 12)) or ("'" in eps) or (eps in ("HT", "ET", "Pen")))

    if is_live:
        base["status"] = "live"
        base["score"] = score_str
        base["minute"] = eps or "LIVE"
        base["league"] = stage_name
        base["league_logo"] = st_logo
        return "live", base
    if is_finished:
        base["status"] = "result"
        base["score"] = score_str
        return "result", base

    base["status"] = "fixture"
    base["time"] = time_lbl or "--:--"
    return "fixture", base


def parse_scoreboard_payload(sb):
    if not isinstance(sb, dict):
        return {}

    details = {}
    iso_str, _, _ = parse_esd(sb.get("Esd"))
    if iso_str:
        details["kickoff_iso"] = iso_str

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
                parsed_stats[label] = {"home": h_st.get(key, 0), "away": a_st.get(key, 0)}
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
        f"https://prod-cdn-public-api.livescore.com/v1/api/app/incidents/soccer/{eid}?locale=en",
    ]
    merged_raw = {}
    for ep in endpoints:
        try:
            resp = await context.request.get(ep, headers=API_HEADERS, timeout=8000)
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


async def scrape_all_live(context):
    live_matches = []
    try:
        resp = await context.request.get(LIVE_API_URL, headers=API_HEADERS, timeout=15000)
        if resp.status == 200:
            data = await resp.json()
            for st in (data.get("Stages") or []):
                for ev in (st.get("Events") or []):
                    bucket, item = parse_event_item(ev, st)
                    if bucket == "live" and item:
                        live_matches.append(item)
        else:
            print(f"⚠️ Live API HTTP {resp.status}")
    except Exception as e:
        print(f"❌ Live API: {e}")

    live_matches = merge_matches(live_matches, [], max_items=120)
    print(f"✅ live: {len(live_matches)} matches")
    return {
        "matches": live_matches,
        "count": len(live_matches),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


async def scrape_date_window(context):
    """Fetch LiveScore's /date/soccer/{YYYYMMDD}/0 JSON API across -2..+14 days in parallel."""
    today = datetime.now(timezone.utc).date()
    dates = [
        (today + timedelta(days=offset)).strftime("%Y%m%d")
        for offset in range(-DATE_WINDOW_PAST_DAYS, DATE_WINDOW_FUTURE_DAYS + 1)
    ]

    by_league = {
        lg["slug"]: {"fixtures": [], "results": [], "league_logo": ""}
        for lg in LEAGUES
    }
    sem = asyncio.Semaphore(API_CONCURRENCY)

    async def fetch_day(ymd):
        url = DATE_API_URL.format(ymd=ymd)
        async with sem:
            try:
                resp = await context.request.get(url, headers=API_HEADERS, timeout=12000)
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("Stages") or []
            except Exception:
                return []

    day_results = await asyncio.gather(*(fetch_day(ymd) for ymd in dates))

    for stages in day_results:
        for st in stages:
            slug = match_stage_to_slug(st)
            if not slug:
                continue
            st_logo = build_logo_url(st.get("BadgeUrl") or st.get("Img") or "")
            if st_logo and not by_league[slug]["league_logo"]:
                by_league[slug]["league_logo"] = st_logo

            for ev in (st.get("Events") or []):
                bucket, item = parse_event_item(ev, st)
                if not item:
                    continue
                if bucket == "fixture":
                    by_league[slug]["fixtures"].append(item)
                elif bucket == "result":
                    by_league[slug]["results"].append(item)

    return by_league


async def scrape_standings_for_league(context, league):
    page = await context.new_page()
    standings = {}
    league_logo = ""
    try:
        await page.goto(league["url"] + "standings/", wait_until="domcontentloaded", timeout=50000)
        try:
            logo_el = await page.query_selector('img[src*="stage"], img[src*="competition"], img.Ok')
            if logo_el:
                league_logo = await logo_el.get_attribute("src") or ""
        except Exception:
            pass
        try:
            await page.wait_for_selector('div[data-id^="rw-"]', timeout=15000)
            standings = await page.evaluate(STANDINGS_JS)
        except Exception as e:
            print(f"⚠️ {league['name']} standings: {e}")
    except Exception as e:
        print(f"❌ {league['name']} standings: {e}")
    finally:
        await page.close()
    return standings, league_logo


async def enrich_matches_with_details(context, payload, details_cache):
    to_fetch = []
    seen_eids = set()

    for m in payload.get("live", {}).get("matches", []):
        eid = m.get("eid")
        if eid and eid not in seen_eids:
            seen_eids.add(eid)
            to_fetch.append(m)

    for lg in payload.get("leagues", {}).values():
        for m in (lg.get("fixtures") or [])[:4]:
            eid = m.get("eid")
            if eid and eid not in seen_eids:
                seen_eids.add(eid)
                if eid in details_cache and details_cache[eid].get("stadium"):
                    m.update(details_cache[eid])
                else:
                    to_fetch.append(m)
        for m in (lg.get("results") or [])[:2]:
            eid = m.get("eid")
            if eid and eid not in seen_eids:
                seen_eids.add(eid)
                if eid in details_cache and details_cache[eid].get("stats"):
                    m.update(details_cache[eid])
                else:
                    to_fetch.append(m)

    batch = to_fetch[:MAX_DETAIL_FETCHES_PER_RUN]
    sem = asyncio.Semaphore(API_CONCURRENCY)

    async def worker(match_obj):
        async with sem:
            info = await fetch_match_details(context, match_obj)
            if info:
                match_obj.update(info)
                eid = match_obj.get("eid")
                if eid:
                    details_cache[eid] = info

    if batch:
        await asyncio.gather(*(worker(m) for m in batch))
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

        # 1. Live matches + 17-day Date API window in parallel (~2 seconds total)
        live_res, date_data = await asyncio.gather(
            scrape_all_live(context),
            scrape_date_window(context),
        )
        payload["live"] = live_res

        # 2. Standings per league
        for league in LEAGUES:
            slug = league["slug"]
            name = league["name"]
            standings, dom_logo = await scrape_standings_for_league(context, league)

            fx = merge_matches(date_data[slug]["fixtures"], [], max_items=60)
            fx.sort(key=lambda m: m.get("kickoff_iso") or "9999")

            rs = merge_matches(date_data[slug]["results"], old_history.get(slug, []), max_items=150)
            rs.sort(key=lambda m: m.get("kickoff_iso") or "", reverse=True)

            standings = attach_form_to_standings(standings, rs)
            team_count = (
                len(standings.get("table", []))
                if standings.get("type") == "single"
                else sum(len(g.get("table", [])) for g in standings.get("groups", []))
            )
            print(f"✅ {name}: {len(fx)} Fix | {len(rs)} Res/Hist | {team_count} Teams")

            payload["leagues"][slug] = {
                "slug": slug,
                "league": name,
                "league_logo": dom_logo or date_data[slug]["league_logo"],
                "fixtures": fx[:40],
                "results": rs[:60],
                "standings": standings,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            new_history[slug] = rs

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
