import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
import os
import json

# --- 1. CONNECTION (DIRECT GOOGLE CLOUD CLIENT) ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("Error: FIREBASE_CREDENTIALS not found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
# This direct client is the only way to target a custom database like 'walid' without errors
db = firestore.Client.from_service_account_info(
    cred_dict, 
    project='tunisia-radios-d7aa8', 
    database='walid'
)

# --- 2. TARGET LIGUE 1 PAGE ---
URL = 'https://www.kawarji.com/resultats/ligue1/2025-2026/25'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def scrape_kawarji_ligue1():
    response = requests.get(URL, headers=HEADERS)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    league_standings = []
    match_results = []

    # --- 3. PARSE STANDINGS TABLE ---
    # The table on the results page has class 'table table-striped table-bordered'
    standings_table = soup.find('table', class_='table-striped')
    if standings_table:
        for row in standings_table.find_all('tr')[1:]: # Skip header row
            cols = row.find_all('td')
            if len(cols) >= 4:
                league_standings.append({
                    "rank": cols[0].get_text(strip=True),
                    "team": cols[1].get_text(strip=True),
                    "played": cols[2].get_text(strip=True),
                    "pts": cols[3].get_text(strip=True)
                })

    # --- 4. PARSE MATCH RESULTS ---
    # Results on this page are inside a specific list or row pattern
    # We look for the match rows specifically
    match_rows = soup.select('.matches_liste .row') or soup.find_all('div', class_='row mb-2')
    for row in match_rows:
        teams = row.find_all('div', class_='col-4')
        score = row.find('div', class_='col-2')
        
        if len(teams) >= 2 and score:
            home = teams[0].get_text(strip=True)
            away = teams[1].get_text(strip=True)
            result = score.get_text(strip=True)
            
            if home and away:
                match_results.append({
                    "home": home,
                    "away": away,
                    "score": result
                })

    return league_standings, match_results

# --- 5. ATOMIC DB SYNC ---
standings, results = scrape_kawarji_ligue1()

if standings:
    db.collection('leagues').document('tunisia_ligue_1').set({
        "table": standings,
        "updated": firestore.SERVER_TIMESTAMP
    })

if results:
    db.collection('leagues').document('fixtures_results').set({
        "matches": results,
        "updated": firestore.SERVER_TIMESTAMP
    })

print(f"Sync Complete: {len(standings)} teams, {len(results)} matches.")
