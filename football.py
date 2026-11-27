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
        req = urllib.request.Request(url, headers={"User-Agent": "TwensaScraper/5.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    print(f"📚 Loaded {label} ({len(data)} entries)")
                    return data
    except Exception:
        print(f"📚 Starting fresh {label}")
    return {}


def clean_cached_details(details_cache):
    """Auto-repair any previously cached stadium strings that were stringified dicts."""
    for eid, info in list(details_cache.items()):
        if not isinstance(info, dict):
            continue
        st = info.get("stadium")
        if isinstance(st, dict):
            raw_name = str(st.get("name") or "")
            if "'Vnm'" in raw_name or '"Vnm"' in raw_name:
                nm = re.search(r"['\"]Vnm['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw_name)
                cy = re.search(r"['\"]Vcy['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw_name)
                if nm:
                    st["name"] = nm.group(1).strip()
                    if cy and not st.get("city"):
                        st["city"] = cy.group(1).strip()
                else:
                    info.pop("stadium", None)
    return details_cache


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
    ccd = (st.get("Ccd") or "").strip().lower()
    scd = (st.get("Scd") or "").strip().lower()
    cnm = (st.get("Cnm") or "").strip().lower()
    comp = (st.get("CompN") or "").strip().lower()
    snm = (st.get("Snm") or "").strip().lower()
    full = f"{ccd} {scd} {cnm} {comp} {snm}"

    if re.search(r"\b(women|woman|feminine|femenina|frauen|u17|u18|u19|u20|u21|u23|youth|reserves?|amateur|futsal)\b", full):
        return ""
