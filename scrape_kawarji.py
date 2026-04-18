import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
import os
import json

# --- 1. CONNECTION ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
cred_dict = json.loads(firebase_secret)
db = firestore.Client.from_service_account_info(
    cred_dict, 
    project='tunisia-radios-d7aa8', 
    database='walid'
)

# --- 2. TARGET LIGUE 1 RESULTS PAGE ---
# This URL contains the data you want without the news clutter
URL = 'https://www.kawarji.com/resultats/ligue1/2025-2026/25'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def scrape_ligue1():
    response = requests.get(URL, headers=HEADERS)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    standings = []
    results = []

    # --- 3. PARSE STANDINGS (TABLE) ---
    # The standings table on this page has the class 'table-striped'
    table = soup.find('table', class_='table-striped')
    if table:
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) >= 4:
                standings.append({
                    "rank": cols[0].text.strip(),
                    "team": cols[1].text.strip(),
                    "j": cols[2].text.strip(),
                    "pts": cols[3].text.strip()
                })

    # --- 4. PARSE RESULTS (MATCHES) ---
    # Kawarji uses specific row structures for scores on this page
    match_items = soup.find_all('div', class_='row mb-2')
    for item in match_items:
        teams = item.find_all('div', class_='col-4')
        score_box = item.find('div', class_='col-2')
        
        if len(teams) >= 2 and score_box:
            home = teams[0].get_text(strip=True)
            away = teams[1].get_text(strip=True)
            score = score_box.get_text(strip=True)
            
            if home and away:
                results.append({
                    "home": home,
                    "away": away,
                    "score": score
                })

    return standings, results

# --- 5. CLEAN UPDATE ---
final_standings, final_results = scrape_ligue1()

if final_standings:
    db.collection('leagues').document('ligue_1_standings').set({
        "data": final_standings,
        "updated": firestore.SERVER_TIMESTAMP
    })

if final_results:
    db.collection('leagues').document('ligue_1_results').set({
        "data": final_results,
        "updated": firestore.SERVER_TIMESTAMP
    })

print(f"Update Successful: {len(final_standings)} teams, {len(final_results)} matches.")
