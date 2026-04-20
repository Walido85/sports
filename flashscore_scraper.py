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

# === HEADERS (mobile + referer) ===
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36",
    "Referer": "https://www.sofascore.com/",
    "Origin": "https://www.sofascore.com",
    "Accept": "application/json",
}

# === LEAGUE CONFIG (tournamentId + current seasonId) ===
LEAGUES = {
    "tunisia_ligue1": {"tournament_id": 984, "season_id": 63748},   # 2025/2026
    "tunisia_ligue2": {"tournament_id": 985, "season_id": 63749},
    "tunisia_cup":    {"tournament_id": 986, "season_id": 63750},
    "premier_league": {"tournament_id": 17,  "season_id": 63699},
    "uefa_champions_league": {"tournament_id": 7, "season_id": 63701},
    "caf_champions_league":  {"tournament_id": 1054, "season_id": 63702},
}

def fetch_live():
    """Get all live + recent football events"""
    url = "https://api.sofascore.com/api/v1/sport/football/events/live"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json().get("events", [])

def fetch_standings(tournament_id: int, season_id: int):
    """Standings for one league"""
    url = f"https://api.sofascore.com/api/v1/unique-tournament/{tournament_id}/season/{season_id}/standings/total"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json().get("standings", [{}])[0].get("rows", [])

def main():
    print(f"🚀 Starting SofaScore API scraper at {datetime.now()}")

    live_events = fetch_live()

    for key, config in LEAGUES.items():
        print(f"\n🔄 Processing {key}...")

        # === MATCHES (live / fixtures / results) ===
        matches = []
        for event in live_events:
            if event.get("tournament", {}).get("id") != config["tournament_id"]:
                continue

            home = event["homeTeam"]["name"]
            away = event["awayTeam"]["name"]
            status = event["status"]["description"]
            score = f"{event['homeScore']['current']}-{event['awayScore']['current']}" if event.get("homeScore") else "-- - --"

            match_dict = {
                "home": home,
                "away": away,
                "date": "",
                "time": status,
                "live_score": score,
                "status": status
            }

            if "FT" in status or "PEN" in status or score != "-- - --":
                db.collection('test').document(f"flashscore_{key}_results").set({"matches": [match_dict], "timestamp": firestore.SERVER_TIMESTAMP}, merge=True)
            elif "'" in status or status.lower() in ["live", "1st", "2nd", "ht"]:
                db.collection('test').document(f"flashscore_{key}_live").set({"matches": [match_dict], "timestamp": firestore.SERVER_TIMESTAMP}, merge=True)
            else:
                db.collection('test').document(f"flashscore_{key}_fixtures").set({"matches": [match_dict], "timestamp": firestore.SERVER_TIMESTAMP}, merge=True)

        # === STANDINGS ===
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

    print("\n🎉 API run completed successfully – check Firestore 'test' collection")

if __name__ == "__main__":
    main()
