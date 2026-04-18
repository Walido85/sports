import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
import os
import json

# --- 1. CONNECTION (STAYS THE SAME) ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
cred_dict = json.loads(firebase_secret)
db = firestore.Client.from_service_account_info(
    cred_dict, 
    project='tunisia-radios-d7aa8', 
    database='walid'
)

# --- 2. FETCH ---
url = 'https://www.kawarji.com/'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
response = requests.get(url, headers=headers)
soup = BeautifulSoup(response.content, 'html.parser')

# --- 3. STANDINGS (CLASSEMENT) ---
def get_standings():
    standings = []
    # Target the table specifically containing the league rankings
    table = soup.find('table', {'class': 'table'}) # Common class for rankings on site
    if not table:
        table = soup.find('table') # Fallback
        
    rows = table.find_all('tr')
    for row in rows:
        cols = row.find_all('td')
        if len(cols) >= 4:
            # Structure: Position | Team | Played | Points
            standings.append({
                "pos": cols[0].get_text(strip=True),
                "team": cols[1].get_text(strip=True),
                "j": cols[2].get_text(strip=True),
                "pts": cols[3].get_text(strip=True)
            })
    return standings

# --- 4. FIXTURES & RESULTS ---
def get_matches():
    matches = []
    # Kawarji uses a specific block for match results/fixtures
    # We look for the "Journée" containers
    match_containers = soup.find_all('div', class_='text-center')
    for container in match_containers:
        text = container.get_text(" ", strip=True)
        # Filters out news; looks for "Team A Score - Score Team B" or "Team A vs Team B"
        if " - " in text or " vs " in text:
            matches.append({"data": text})
    return matches

# --- 5. EXECUTE & SAVE ---
final_standings = get_standings()
final_matches = get_matches()

if final_standings:
    db.collection('leagues').document('tunisia_ligue_1').set({
        "last_update": firestore.SERVER_TIMESTAMP,
        "table": final_standings
    })
    print("Standings Synced.")

if final_matches:
    db.collection('leagues').document('fixtures_results').set({
        "last_update": firestore.SERVER_TIMESTAMP,
        "matches": final_matches
    })
    print("Fixtures/Results Synced.")
