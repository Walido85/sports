import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# --- 1. FIRESTORE CONNECTION ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("FATAL: Secret FIREBASE_CREDENTIALS not found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
cred = credentials.Certificate(cred_dict)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'projectId': 'tunisia-radios-d7aa8'
    })

# We use 'database_id' specifically for the 'walid' database
db = firestore.client(database_id='walid')

# --- 2. AGGRESSIVE SCRAPING ---
URL = 'https://www.kawarji.com/resultats/ligue1/2025-2026/25'
# Realistic browser headers to prevent being blocked
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://www.google.com/'
}

def get_data():
    try:
        response = requests.get(URL, headers=HEADERS, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        league_standings = []
        match_results = []

        # --- A. CLASSEMENT (TABLE) ---
        # We search for ANY table containing the text 'Pts'
        target_table = None
        for table in soup.find_all('table'):
            if 'pts' in table.get_text().lower():
                target_table = table
                break
        
        if target_table:
            for row in target_table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    league_standings.append({
                        "rank": cols[0].get_text(strip=True),
                        "team": cols[1].get_text(strip=True),
                        "j": cols[2].get_text(strip=True),
                        "pts": cols[3].get_text(strip=True)
                    })

        # --- B. RESULTS ---
        # Look specifically for the rows that represent matches
        for row in soup.find_all('div', class_='row'):
            teams = row.find_all('div', class_='col-4')
            score = row.find('div', class_='col-2')
            if len(teams) >= 2 and score:
                home = teams[0].get_text(strip=True)
                away = teams[1].get_text(strip=True)
                res = score.get_text(strip=True)
                # Ensure it's not empty and contains a digit or 'vs'
                if home and away and (any(c.isdigit() for c in res) or 'vs' in res.lower()):
                    match_results.append({"home": home, "away": away, "score": res})

        return league_standings, match_results
    except Exception as e:
        print(f"Connection/Parsing Error: {e}")
        return [], []

# --- 3. DATABASE UPDATE ---
standings, results = get_data()

if standings:
    db.collection('leagues').document('tunisia_ligue_1').set({
        "table": standings,
        "updated": firestore.SERVER_TIMESTAMP
    })
    print(f"Successfully pushed {len(standings)} teams.")
else:
    print("Failed to find Standings Table. Check URL/Selectors.")

if results:
    db.collection('leagues').document('fixtures_results').set({
        "matches": results,
        "updated": firestore.SERVER_TIMESTAMP
    })
    print(f"Successfully pushed {len(results)} matches.")
else:
    print("Failed to find Results. Check URL/Selectors.")
