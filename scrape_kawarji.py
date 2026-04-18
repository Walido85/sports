import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# --- 1. CONNECT TO FIRESTORE ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if firebase_secret:
    cred_dict = json.loads(firebase_secret)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
else:
    print("Error: FIREBASE_CREDENTIALS secret not found.")
    exit(1)

# --- 2. FETCH KAWARJI ---
url = 'https://www.kawarji.com/'
headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
response = requests.get(url, headers=headers)

if response.status_code == 200:
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # --- 3. SCRAPE STANDINGS ---
    standings = []
    # NOTE: You will need to replace 'REPLACE_ME_STANDINGS_CLASS' later
    table = soup.find('table', class_='REPLACE_ME_STANDINGS_CLASS')
    if table:
        rows = table.find_all('tr')[1:] 
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 4:
                standings.append({
                    "position": cols[0].text.strip(),
                    "team": cols[1].text.strip(),
                    "played": cols[2].text.strip(),
                    "points": cols[3].text.strip()
                })
        if standings:
            db.collection('sports_data').document('standings_ligue1').set({"table": standings})
            print("Standings updated!")

    # --- 4. SCRAPE LIVE SCORES ---
    live_matches = []
    # NOTE: You will need to replace these classes later
    for match in soup.find_all('div', class_='REPLACE_ME_LIVE_CLASS'): 
        try:
            live_matches.append({
                "team1": match.find('span', class_='REPLACE_TEAM1_CLASS').text.strip(),
                "team2": match.find('span', class_='REPLACE_TEAM2_CLASS').text.strip(),
                "score": match.find('span', class_='REPLACE_SCORE_CLASS').text.strip()
            })
        except AttributeError:
            continue
    if live_matches:
        db.collection('sports_data').document('live_scores').set({"matches": live_matches})
        print("Live scores updated!")

    print("Scrape run finished.")

else:
    print(f"Failed to load Kawarji. Status Code: {response.status_code}")
