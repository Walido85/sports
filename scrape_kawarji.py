import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials
from google.cloud import firestore
import os
import json

# --- 1. FIRESTORE CONNECTION ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
cred_dict = json.loads(firebase_secret)
db = firestore.Client.from_service_account_info(
    cred_dict, 
    project='tunisia-radios-d7aa8', 
    database='walid'
)

# --- 2. TARGETING CONFIGURATION ---
URL = 'https://www.kawarji.com/'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def scrape_kawarji():
    response = requests.get(URL, headers=HEADERS)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    league_data = []
    match_data = []

    # --- 3. PARSE STANDINGS (CLASSEMENT) ---
    # Senior fix: Locate table by headers specifically
    tables = soup.find_all('table')
    for table in tables:
        header_text = table.get_text().lower()
        if 'pts' in header_text and 'j.' in header_text:
            rows = table.find_all('tr')
            for row in rows[1:]:  # Skip headers
                cols = row.find_all('td')
                if len(cols) >= 4:
                    league_data.append({
                        "rank": cols[0].get_text(strip=True).replace('.', ''),
                        "team": cols[1].get_text(strip=True),
                        "played": cols[2].get_text(strip=True),
                        "points": cols[3].get_text(strip=True)
                    })
            break # Found the main table

    # --- 4. PARSE RESULTS & FIXTURES ---
    # Senior fix: Kawarji lists results in 'li' elements under specific headers
    # We look for containers that have score patterns (Number : Number) or (Time)
    items = soup.find_all(['li', 'div', 'td'])
    for item in items:
        text = item.get_text(" ", strip=True)
        # Regex-like check for "Team A 1 - 0 Team B" or "Team A vs Team B"
        # Must be short to avoid news headlines
        if (("-" in text or ":" in text or "vs" in text) and len(text) < 80):
            # Extra filter to ensure it's a match, not a date or news
            if any(char.isdigit() for char in text) and len(text) > 10:
                match_data.append({"match": text})

    return league_data, match_data

# --- 5. ATOMIC DB WRITE ---
standings, matches = scrape_kawarji()

if standings:
    db.collection('leagues').document('tunisia_ligue_1').set({
        "table": standings,
        "updated": firestore.SERVER_TIMESTAMP
    })

if matches:
    # We use a unique document for fixtures to keep the collection clean
    db.collection('leagues').document('fixtures_results').set({
        "matches": matches,
        "updated": firestore.SERVER_TIMESTAMP
    })

print(f"Sync Complete. {len(standings)} teams and {len(matches)} matches updated.")
