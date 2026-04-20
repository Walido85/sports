import requests
import json
import os
import time
from datetime import datetime
from google.cloud import firestore
from google.oauth2 import service_account

# === FIRESTORE ===
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("No FIREBASE_CREDENTIALS found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project='tunisia-radios-d7aa8', credentials=credentials, database='walid')
print("Firestore connected → collection 'test'")

# === STRONGEST HEADERS (iPhone + full browser simulation) ===
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
})

# === LEAGUE CONFIG ===
LEAGUES = {
    "tunisia_ligue1": {"tournament_id": 984, "season_id": 63748},
    "tunisia_ligue2": {"tournament_id": 985, "season_id": 63749},
    "tunisia_cup":    {"tournament_id": 986, "season_id": 63750},
    "premier_league": {"tournament_id": 17,  "season_id": 63699},
    "uefa_champions_league": {"tournament_id": 7, "season_id": 63701},
    "caf_champions_league":  {"tournament_id": 1054, "season_id": 63702},
}

def fetch_with_retry(url, max_retries=3):
    for attempt in range(max_retries):
        try:
            time.sleep(1.5)  # human-like delay
            r = SESSION.get(url, timeout=20)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            if r.status_code == 403 and attempt < max_retries - 1:
                print(f"403 detected – retry {attempt+1}/{max_retries}")
                time.sleep(3)
                continue
            raise
    raise Exception("Max retries exceeded")

def fetch_live():
    url = "https://api.sofascore.com/api/v1/sport/football/events/live"
    return fetch_with_retry(url).get("events", [])

def fetch_standings(tournament_id: int, season_id: int):
    url = f"https://api.sofascore.com/api/v1/unique-tournament/{tournament_id}/season/{season_id}/standings/total"
    data = fetch_with_retry(url)
    return data.get("standings", [{}])[0].get("rows", [])

def main():
    print(f"🚀 Starting SofaScore API scraper at {datetime.now()}")

    live_events = fetch_live()

    for key, config in LEAGUES.items():
        print(f"\n🔄 Processing {key}...")

        # MATCHES
        for event in live_events:
            if event.get("tournament", {}).get("id") != config["tournament_id"]:
                continue

            home = event.get("homeTeam", {}).get("name", "N/A")
            away = event.get("awayTeam", {}).get("name", "N/A")
            status = event.get("status", {}).get("description", "")
            score = f"{event.get('homeScore', {}).get('current', 0)}-{event.get('awayScore', {}).get('current', 0)}"

            match_dict = {
                "home": home,
                "away": away,
                "date": "",
                "time": status,
                "live_score": score,
                "status": status
            }

            if "FT" in status.upper() or "PEN" in status.upper() or score != "0-0":
                db.collection('test').document(f"flashscore_{key}_results").set({"matches": [match_dict], "timestamp": firestore.SERVER_TIMESTAMP}, merge=True)
            elif "'" in status or status.lower() in ["live", "1st", "2nd", "ht"]:
                db.collection('test').document(f"flashscore_{key}_live").set({"matches": [match_dict], "timestamp": firestore.SERVER_TIMESTAMP}, merge=True)
            else:
                db.collection('test').document(f"flashscore_{key}_fixtures").set({"matches": [match_dict], "timestamp": firestore.SERVER_TIMESTAMP}, merge=True)

        # STANDINGS
        standings_rows = fetch_standings(config["tournament_id"], config["season_id"])
        table = []
        for row in standings_rows:
            table.append({
                "position": str(row.get("position", "")),
                "team": row.get("team", {}).get("name", ""),
                "played": str(row.get("matches", "")),
                "wins": str(row.get("wins", "")),
                "draws": str(row.get("draws", "")),
                "losses": str(row.get("losses", "")),
                "goals": f"{row.get('goalsScored', '')}:{row.get('goalsConceded', '')}",
                "points": str(row.get("points", ""))
            })

        if table:
            db.collection('test').document(f"flashscore_{key}_standings").set({"table": table, "timestamp": firestore.SERVER_TIMESTAMP})
            print(f"✅ Saved {len(table)} STANDINGS for {key}")
        else:
            print(f"⚠️ No standings for {key}")

    print("\n🎉 API run completed – check Firestore 'test' collection")

if __name__ == "__main__":
    main()
