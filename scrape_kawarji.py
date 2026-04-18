import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
from datetime import datetime

# --- 1. FIREBASE CONFIGURATION ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("Error: FIREBASE_CREDENTIALS secret missing.")
    exit(1)

cred_dict = json.loads(firebase_secret)
cred = credentials.Certificate(cred_dict)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {'projectId': 'tunisia-radios-d7aa8'})

# Targeting your 'walid' database
db = firestore.client(database_id='walid')

def scrape_kawarji():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    
    # --- PART A: CLASSEMENT (STANDINGS) ---
    standings_url = "https://www.kawarji.com/classement/premier-league/2025-2026"
    standings = []
    
    try:
        res_s = requests.get(standings_url, headers=headers, timeout=20)
        soup_s = BeautifulSoup(res_s.content, 'html.parser')
        
        # Exact selector from your Node.js script and .mht analysis
        table = soup_s.find('table', class_='table-classement')
        if table:
            for i, row in enumerate(table.find_all('tr')):
                if i == 0: continue # Skip header
                cols = row.find_all('td')
                if len(cols) >= 6:
                    standings.append({
                        "rank": cols[0].get_text(strip=True),
                        "team": cols[1].get_text(strip=True),
                        "played": cols[2].get_text(strip=True),
                        "gd": cols[4].get_text(strip=True),
                        "pts": cols[5].get_text(strip=True)
                    })
        print(f"Scraped {len(standings)} standing entries.")
    except Exception as e:
        print(f"Standings Error: {e}")

    # --- PART B: RESULTATS (MATCHES) ---
    # Based on the J25 URL you focus on
    results_url = "https://www.kawarji.com/resultats/ligue1/2025-2026/25"
    matches = []
    
    try:
        res_m = requests.get(results_url, headers=headers, timeout=20)
        soup_m = BeautifulSoup(res_m.content, 'html.parser')
        
        # Pattern from .mht: Matches are in 'row mb-2' blocks
        match_rows = soup_m.find_all('div', class_='row mb-2')
        for row in match_rows:
            teams = row.find_all('div', class_='col-4')
            score_box = row.find('div', class_='col-2')
            
            if len(teams) >= 2 and score_box:
                home = teams[0].get_text(strip=True)
                away = teams[1].get_text(strip=True)
                score = score_box.get_text(strip=True)
                if home and away:
                    matches.append({"home": home, "away": away, "score": score})
        print(f"Scraped {len(matches)} match results.")
    except Exception as e:
        print(f"Results Error: {e}")

    return standings, matches

# --- 3. DATABASE SYNC ---
s_data, m_data = scrape_kawarji()

# Save Standings
if s_data:
    db.collection('sports_data').document('ligue-1-standings').set({
        "lastUpdated": datetime.utcnow().isoformat(),
        "standings": s_data
    })

# Save Results
if m_data:
    db.collection('sports_data').document('ligue-1-results').set({
        "lastUpdated": datetime.utcnow().isoformat(),
        "matches": m_data
    })

print("Process finished.")
