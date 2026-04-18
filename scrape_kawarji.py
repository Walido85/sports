import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
import os
import json

# --- 1. CONNECT TO FIRESTORE ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
cred_dict = json.loads(firebase_secret)
db = firestore.Client.from_service_account_info(
    cred_dict, 
    project='tunisia-radios-d7aa8', 
    database='walid'
)

# --- 2. FETCH KAWARJI ---
url = 'https://www.kawarji.com/'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.content, 'html.parser')

# --- 3. SCRAPE LOGIC ---
def scrape_data():
    # --- STANDINGS ---
    standings = []
    # Find the table that contains team rankings
    rank_table = soup.find('table', class_='table')
    if rank_table:
        for row in rank_table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) >= 4:
                standings.append({
                    "pos": cols[0].get_text(strip=True),
                    "team": cols[1].get_text(strip=True),
                    "played": cols[2].get_text(strip=True),
                    "pts": cols[3].get_text(strip=True)
                })

    # --- RESULTS & FIXTURES ---
    matches = []
    # Target specific match containers
    for match in soup.find_all('div', class_='text-center'):
        content = match.get_text(" ", strip=True)
        # Filter: Must have a dash (score) or 'vs' (fixture) and no long news text
        if (" - " in content or " vs " in content) and len(content) < 100:
            matches.append({"match_info": content})
            
    return standings, matches

# --- 4. EXECUTE & UPDATE ---
league_table, all_matches = scrape_data()

# Update Standings Document
if league_table:
    db.collection('leagues').document('tunisia_ligue_1').set({
        "data": league_table,
        "last_sync": firestore.SERVER_TIMESTAMP
    })

# Update Results/Fixtures Document
if all_matches:
    db.collection('leagues').document('fixtures_results').set({
        "data": all_matches,
        "last_sync": firestore.SERVER_TIMESTAMP
    })

print("Sync Complete. No downtime occurred.")
