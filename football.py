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

RAW = "https://raw.githubusercontent.com/Walido85/sports/data/"
HISTORY_URL = RAW + "history.json"
DETAILS_URL = RAW + "match_details.json"

API_BASE = "https://prod-cdn-public-api.livescore.com/v1/api/app/"
LIVE_API = API_BASE + "live/soccer/0?countryCode=TN&locale=en"
DATE_API = API_BASE + "date/soccer/{ymd}/0?countryCode=TN&locale=en"
LOGO_CDN = "https://lsm-static-prod.livescore.com/medium/"
SITE = "https://www.livescore.com/en/football/"

PAST_DAYS = 2
FUTURE_DAYS = 14
CONCURRENCY = 6
MAX_DETAILS = 20

LEAGUES = [
    ("tunisia-ligue-1", "Tunisia Ligue 1", "tunisia/ligue-i/"),
    ("premier-league", "Premier League", "england/premier-league/"),
    ("laliga", "LaLiga", "spain/laliga/"),
    ("serie-a", "Serie A", "italy/serie-a/"),
    ("bundesliga", "Bundesliga", "germany/bundesliga/"),
    ("ligue-1", "Ligue 1", "france/ligue-1/"),
    ("uefa-champions-league", "UEFA Champions League", "europe/champions-league/"),
    ("uefa-europa-league", "UEFA Europa League", "europe/europa-league/"),
    ("caf-champions-league", "CAF Champions League", "africa/caf-champions-league/"),
]

HEADERS = {
    "Accept": "application/json",
    "Origin": "https://www.livescore.com",
    "Referer": "https://www.livescore.com/",
}

STANDINGS_JS = r"""() => {
  function getStats(tid) {
    const divs = document.querySelectorAll('div[data-id^="' + tid + '_"]');
    let sfx = "";
    for (const d of divs) {
      const id = d.getAttribute('data-id') || "";
      if (id.endsWith('_played')) {
        sfx = id.replace(tid + '_', '').replace('_played', '');
        break;
      }
    }
    if (!sfx) {
      return {
        played: "0", wins: "0", draws: "0", losses: "0",
        goals_for: "0", goals_against: "0", goal_diff: "0", points: "0"
      };
    }
    const g = (k) => {
      const sel = 'div[data-id="' + tid + '_' + sfx + '_' + k + '"]';
      return document.querySelector(sel)?.innerText?.trim() || "0";
    };
    return {
      played: g('played'), wins: g('wins'), draws: g('draws'),
      losses: g('losses'), goals_for: g('goalsFor'),
      goals_against: g('goalsAgainst'), goal_diff: g('goalsDiff'),
      points: g('points')
    };
  }

  function parseRow(row) {
    const tid = (row.getAttribute('data-id') || "").replace('rw-', '');
    const nmCell = row.querySelector('div[data-id="c-nm"]');
    if (!nmCell) return null;
    const posTxt = row.querySelector('div[data-id="c-pos"]')?.innerText || "";
    const pos = (posTxt.trim().match(/\d+/) || [""])[0];
    const link = nmCell.querySelector('a') || nmCell;
    const team = (link.innerText || "").split('\n')[0].trim();
    const logo = nmCell.querySelector('img')?.src || "";
    if (!team) return null;
    return { position: pos, team, team_logo: logo, ...getStats(tid) };
  }

  const subs = document.querySelectorAll('div[data-id^="lt-tb-all-"]');
  if (subs.length > 1) {
    const groups = [];
    for (const sub of subs) {
      const tabId = sub.getAttribute('data-id').replace('lt-tb-all-', '');
      const tabEl =
        document.querySelector('div[data-id="lt-tb-all-' + tabId + '-hdr"]') ||
        document.querySelector('a[id="' + tabId + '__tab"]') ||
        document.querySelector('div[id="tb-it_' + tabId + '"] a');
      const raw = (tabEl?.innerText?.trim() || "").replace(/\s+/g, " ");
      const gname = (raw && !raw.startsWith("#")) ? raw : "";
      const table = [];
      for (const row of sub.querySelectorAll('div[data-id^="rw-"]')) {
        const e = parseRow(row);
        if (e && !table.some(t => t.team === e.team)) table.push(e);
      }
      if (table.length) groups.push({ name: gname, table });
    }
    if (groups.length === 1) return { type: "single", table: groups[0].table };
    if (groups.length > 1) return { type: "groups", groups };
  }

  const table = [];
  for (const row of document.querySelectorAll('div[data-id^="rw-"]')) {
    const e = parseRow(row);
    if (e && !table.some(t => t.team === e.team)) table.push(e);
  }
  return { type: "single", table };
}"""


def load_json(url, label):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Twensa/5.2"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                if isinstance(data, dict):
                    print(f"Loaded {label} ({len(data)} entries)")
                    return data
    except Exception:
        print(f"Starting fresh {label}")
    return {}


def clean_cache(cache):
    for info in cache.values():
        if not isinstance(info, dict):
            continue
        st = info.get("stadium")
        if isinstance(st, dict):
            raw = str(st.get("name") or "")
            if "'Vnm'" in raw or '"Vnm"' in raw:
                nm = re.search(r"['\"]Vnm['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw)
                cy = re.search(r"['\"]Vcy['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw)
                if nm:
                    st["name"] = nm.group(1).strip()
                    if cy and not st.get("city"):
                        st["city"] = cy.group(1).strip()
                else:
                    info.pop("stadium", None)
    return cache


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def merge_matches(new_items, old_items, limit=150):
    out, seen = [], set()
    for it in (new_items + old_items):
        eid = str(it.get("eid") or "")
        key = eid or f"{norm(it.get('home'))}|{norm(it.get('away'))}|{it.get('date', '')}"
        if key not in seen:
            seen.add(key)
            out.append(it)
        if len(out) >= limit:
            break
    return out


def parse_esd(esd):
    s = str(esd or "").strip()
    if len(s) == 14 and s.isdigit():
        try:
            dt = datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
            return dt.isoformat(), dt.strftime("%d %b").upper(), dt.strftime("%H:%M")
        except Exception:
            pass
    return "", "", ""


def logo_url(path):
    if not path:
        return ""
    s = str(path).strip()
    return s if s.startswith("http") else (LOGO_CDN + s.lstrip("/"))


def stage_to_slug(st):
    ccd = (st.get("Ccd") or "").strip().lower()
    scd = (st.get("Scd") or "").strip().lower()
    cnm = (st.get("Cnm") or "").strip().lower()
    comp = (st.get("CompN") or "").strip().lower()
    snm = (st.get("Snm") or "").strip().lower()
    full = f"{ccd} {scd} {cnm} {comp} {snm}"

    bad = r"\b(women|woman|feminine|femenina|frauen|u17|u18|u19|u20|u21|u23|youth|reserves?|amateur|futsal)\b"
    if re.search(bad, full):
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
    if "champions-league" in ccd or "champions-league" in scd or "champions league" in comp or "champions league" in cnm:
        if not any(x in full for x in ("caf", "afc", "concacaf", "ofc", "africa", "asia", "arab", "gulf")):
            return "uefa-champions-league"
    if "europa-league" in ccd or "europa-league" in scd or "europa league" in comp or "europa league" in cnm:
        if "conference" not in full:
            return "uefa-europa-league"
    return ""


def parse_event(ev, st):
    t1l, t2l = ev.get("T1") or [], ev.get("T2") or []
    if not t1l or not t2l:
        return None, None
    t1 = t1l[0] if isinstance(t1l[0], dict) else {}
    t2 = t2l[0] if isinstance(t2l[0], dict) else {}
    home = (t1.get("Nm") or "").strip()
    away = (t2.get("Nm") or "").strip()
    if not home or not away:
        return None, None

    eid = str(ev.get("Eid") or "")
    iso_s, d_lbl, t_lbl = parse_esd(ev.get("Esd"))
    epr, esid = ev.get("Epr"), ev.get("Esid")
    eps = str(ev.get("Eps") or "").strip()
    tr1, tr2 = ev.get("Tr1"), ev.get("Tr2")
    ok_sc = tr1 is not None and tr2 is not None and str(tr1) != "" and str(tr2) != ""
    score = f"{tr1} - {tr2}" if ok_sc else "-- - --"

    st_name = st.get("CompN") or st.get("Snm") or st.get("Cnm") or "Other"
    st_logo = logo_url(st.get("BadgeUrl") or st.get("Img") or "")

    base = {
        "eid": eid, "home": home, "away": away,
        "home_logo": logo_url(t1.get("Img")),
        "away_logo": logo_url(t2.get("Img")),
        "date": d_lbl, "kickoff_iso": iso_s,
        "round": st.get("Snm") or "", "timezone": "UTC",
    }

    done = (epr == 2) or (esid in (6, 13)) or (eps in ("FT", "AET", "AP", "Canc.", "Postp."))
    live = (not done) and ((epr == 1) or (esid in (2, 3, 4, 5, 10, 11, 12)) or ("'" in eps) or (eps in ("HT", "ET", "Pen")))

    if live:
        base.update({"status": "live", "score": score, "minute": eps or "LIVE", "league": st_name, "league_logo": st_logo})
        return "live", base
    if done:
        base.update({"status": "result", "score": score})
        return "result", base
    base.update({"status": "fixture", "time": t_lbl or "--:--"})
    return "fixture", base


def parse_details(sb):
    if not isinstance(sb, dict):
        return {}
    out = {}
    iso_s, _, _ = parse_esd(sb.get("Esd"))
    if iso_s:
        out["kickoff_iso"] = iso_s

    vo = sb.get("Venue")
    if isinstance(vo, dict):
        vn = vo.get("Vnm") or vo.get("Nm") or ""
        vc = vo.get("Vcy") or vo.get("Vct") or vo.get("City") or ""
        vco = vo.get("Vco") or vo.get("Cn") or ""
    else:
        vn = sb.get("Vnm") or (vo if isinstance(vo, str) else "")
        vc = sb.get("Vcy") or sb.get("Vct") or sb.get("City") or ""
        vco = sb.get("Vco") or ""
    if vn:
        out["stadium"] = {"name": str(vn).strip(), "city": str(vc).strip(), "country": str(vco).strip()}

    refs = sb.get("Refs") or []
    if isinstance(refs, list) and refs:
        r0 = refs[0]
        if isinstance(r0, dict) and (r0.get("Nm") or r0.get("Kn")):
            out["referee"] = {"name": str(r0.get("Nm") or r0.get("Kn")).strip(), "country": str(r0.get("Cn") or "").strip()}
        elif isinstance(r0, str) and r0.strip():
            out["referee"] = {"name": r0.strip(), "country": ""}

    if sb.get("Vsp"):
        out["attendance"] = str(sb.get("Vsp"))

    raw_st = sb.get("Stat") or []
    if isinstance(raw_st, list) and len(raw_st) >= 2:
        hs = raw_st[0] if isinstance(raw_st[0], dict) else {}
        as_ = raw_st[1] if isinstance(raw_st[1], dict) else {}
        smap = [
            ("possession", "Pss"), ("shots_on_target", "Shon"),
            ("shots_off_target", "Shof"), ("shots_blocked", "Shbl"),
            ("corners", "Cos"), ("offsides", "Ofs"), ("fouls", "Fls"),
            ("yellow_cards", "Ycs"), ("red_cards", "Rcs"), ("saves", "Gks"),
        ]
        stats = {lbl: {"home": hs.get(k, 0), "away": as_.get(k, 0)} for lbl, k in smap if k in hs or k in as_}
        if stats:
            out["stats"] = stats

    incs = sb.get("Incs") or {}
    events = []
    if isinstance(incs, dict):
        imap = {36: "goal", 37: "penalty_goal", 39: "own_goal", 43: "yellow_card", 44: "second_yellow", 45: "red_card"}
        for hk in sorted(incs.keys()):
            for inc in (incs.get(hk) or []):
                if not isinstance(inc, dict) or inc.get("IT") not in imap:
                    continue
                mn = str(inc.get("Min", "")) + (f"+{inc['MinEx']}" if inc.get("MinEx") else "")
                sub = inc.get("Incs")
                assist = sub[0].get("Pn", "") if isinstance(sub, list) and sub and isinstance(sub[0], dict) else ""
                events.append({
                    "minute": mn, "type": imap[inc["IT"]],
                    "team": "home" if inc.get("Nm") == 1 else "away",
                    "player": inc.get("Pn") or "", "assist": assist,
                })
    if events:
        out["events"] = events

    lus = sb.get("Lu") or []
    if isinstance(lus, list) and len(lus) >= 2:
        lineups = {}
        for i, side in enumerate(("home", "away")):
            lu = lus[i] if isinstance(lus[i], dict) else {}
            fo = "-".join(str(x) for x in lu.get("Fo", [])) if isinstance(lu.get("Fo"), list) else ""
            starters, subs, coach = [], [], ""
            for pl in (lu.get("Ps") or []):
                if not isinstance(pl, dict):
                    continue
                pn, pnum, ppos = pl.get("Snm") or pl.get("Ln") or "", pl.get("Snu") or "", pl.get("Pos")
                if ppos == 1:
                    coach = pn
                elif pl.get("Pon") == "SUB" or (isinstance(ppos, int) and ppos >= 6):
                    subs.append({"name": pn, "number": pnum})
                else:
                    starters.append({"name": pn, "number": pnum})
            if fo or starters or coach:
                lineups[side] = {"formation": fo, "coach": coach, "starters": starters[:11], "subs": subs[:12]}
        if lineups:
            out["lineups"] = lineups
    return out


async def fetch_details(ctx, m):
    eid = m.get("eid")
    if not eid:
        return {}
    merged = {}
    for ep in ("scoreboard", "info", "statistics", "incidents", "lineups"):
        try:
            r = await ctx.request.get(f"{API_BASE}{ep}/soccer/{eid}?locale=en", headers=HEADERS, timeout=8000)
            if r.status == 200:
                part = await r.json()
                if isinstance(part, dict):
                    merged.update(part)
        except Exception:
            continue
    return parse_details(merged)


def attach_form(standings, results):
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

    def fill(tbl):
        for r in tbl:
            r["form"] = forms.get(norm(r.get("team")), [])

    if isinstance(standings, dict):
        if standings.get("type") == "single" and standings.get("table"):
            fill(standings["table"])
        elif standings.get("type") == "groups" and standings.get("groups"):
            for g in standings["groups"]:
                if g.get("table"):
                    fill(g["table"])
    return standings


async def scrape_live(ctx):
    out = []
    try:
        r = await ctx.request.get(LIVE_API, headers=HEADERS, timeout=15000)
        if r.status == 200:
            data = await r.json()
            for st in (data.get("Stages") or []):
                for ev in (st.get("Events") or []):
                    b, it = parse_event(ev, st)
                    if b == "live" and it:
                        out.append(it)
    except Exception as e:
        print(f"Live API error: {e}")
    out = merge_matches(out, [], limit=120)
    print(f"live: {len(out)} matches")
    return {"matches": out, "count": len(out), "updated_at": datetime.now(timezone.utc).isoformat()}


async def scrape_dates(ctx):
    today = datetime.now(timezone.utc).date()
    days = [(today + timedelta(days=d)).strftime("%Y%m%d") for d in range(-PAST_DAYS, FUTURE_DAYS + 1)]
    by_lg = {slug: {"fixtures": [], "results": [], "league_logo": ""} for slug, _, _ in LEAGUES}
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one_day(ymd):
        async with sem:
            try:
                r = await ctx.request.get(DATE_API.format(ymd=ymd), headers=HEADERS, timeout=12000)
                return (await r.json()).get("Stages") or [] if r.status == 200 else []
            except Exception:
                return []

    for stages in await asyncio.gather(*(one_day(d) for d in days)):
        for st in stages:
            slug = stage_to_slug(st)
            if not slug:
                continue
            lg_logo = logo_url(st.get("BadgeUrl") or st.get("Img") or "")
            if lg_logo and not by_lg[slug]["league_logo"]:
                by_lg[slug]["league_logo"] = lg_logo
            for ev in (st.get("Events") or []):
                b, it = parse_event(ev, st)
                if b == "fixture":
                    by_lg[slug]["fixtures"].append(it)
                elif b == "result":
                    by_lg[slug]["results"].append(it)
    return by_lg


async def scrape_standings(ctx, name, path):
    page = await ctx.new_page()
    st, lg_logo = {}, ""
    try:
        await page.goto(SITE + path + "standings/", wait_until="domcontentloaded", timeout=50000)
        try:
            el = await page.query_selector('img[src*="stage"], img[src*="competition"], img.Ok')
            if el:
                lg_logo = await el.get_attribute("src") or ""
        except Exception:
            pass
        try:
            await page.wait_for_selector('div[data-id^="rw-"]', timeout=15000)
            st = await page.evaluate(STANDINGS_JS)
        except Exception as e:
            print(f"{name} standings warn: {e}")
    except Exception as e:
        print(f"{name} standings err: {e}")
    finally:
        await page.close()
    return st, lg_logo


async def enrich_all(ctx, payload, cache):
    todo, seen = [], set()
    for m in payload.get("live", {}).get("matches", []):
        eid = m.get("eid")
        if eid and eid not in seen:
            seen.add(eid)
            todo.append(m)
    for lg in payload.get("leagues", {}).values():
        for m in (lg.get("fixtures") or [])[:4]:
            eid = m.get("eid")
            if eid and eid not in seen:
                seen.add(eid)
                if eid in cache and cache[eid].get("stadium"):
                    m.update(cache[eid])
                else:
                    todo.append(m)
        for m in (lg.get("results") or [])[:2]:
            eid = m.get("eid")
            if eid and eid not in seen:
                seen.add(eid)
                if eid in cache and cache[eid].get("stats"):
                    m.update(cache[eid])
                else:
                    todo.append(m)

    batch = todo[:MAX_DETAILS]
    sem = asyncio.Semaphore(CONCURRENCY)

    async def work(m):
        async with sem:
            info = await fetch_details(ctx, m)
            if info:
                m.update(info)
                if m.get("eid"):
                    cache[m["eid"]] = info

    if batch:
        await asyncio.gather(*(work(m) for m in batch))
        print(f"Enriched {len(batch)} matches")

    for lg in payload.get("leagues", {}).values():
        for b in ("fixtures", "results"):
            for m in lg.get(b, []):
                eid = m.get("eid")
                if eid and eid in cache:
                    for k, v in cache[eid].items():
                        m.setdefault(k, v)

    if len(cache) > 500:
        keys = list(cache.keys())[-500:]
        cache = {k: cache[k] for k in keys}
    return cache


async def main():
    old_hist = load_json(HISTORY_URL, "history")
    cache = clean_cache(load_json(DETAILS_URL, "match_details"))
    new_hist = {}
    payload = {"updated_at": datetime.now(timezone.utc).isoformat(), "live": {}, "leagues": {}}

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            timezone_id="UTC",
            locale="en-GB",
        )
        live_res, date_data = await asyncio.gather(scrape_live(ctx), scrape_dates(ctx))
        payload["live"] = live_res

        for slug, name, path in LEAGUES:
            st, dom_logo = await scrape_standings(ctx, name, path)
            fx = merge_matches(date_data[slug]["fixtures"], [], limit=60)
            fx.sort(key=lambda m: m.get("kickoff_iso") or "9999")
            rs = merge_matches(date_data[slug]["results"], old_hist.get(slug, []), limit=150)
            rs.sort(key=lambda m: m.get("kickoff_iso") or "", reverse=True)
            st = attach_form(st, rs)
            t_cnt = len(st.get("table", [])) if st.get("type") == "single" else sum(len(g.get("table", [])) for g in st.get("groups", []))
            print(f"{name}: {len(fx)} Fix | {len(rs)} Res | {t_cnt} Teams")
            payload["leagues"][slug] = {
                "slug": slug, "league": name,
                "league_logo": dom_logo or date_data[slug]["league_logo"],
                "fixtures": fx[:40], "results": rs[:60], "standings": st,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            new_hist[slug] = rs

        cache = await enrich_all(ctx, payload, cache)
        await browser.close()

    os.makedirs("public", exist_ok=True)
    with open("public/football.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    with open("public/history.json", "w", encoding="utf-8") as f:
        json.dump(new_hist, f, ensure_ascii=False, separators=(",", ":"))
    with open("public/match_details.json", "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, separators=(",", ":"))
    print("Saved public/football.json, history.json & match_details.json")


if __name__ == "__main__":
    asyncio.run(main())
