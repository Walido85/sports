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
    
    # --- 3. SMART SCRAPE STANDINGS ---
    standings = []
    # Finds any table on the page that contains the word "équipe" (team)
    table = soup.find(lambda tag: tag.name == 'table' and 'équipe' in tag.text.lower())
    
    if table:
        rows = table.find_all('tr')[1:] # Skip the header row
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
            print("Standings updated successfully!")

    # --- 4. SMART SCRAPE LIVE SCORES / DIRECTS ---
    live_matches = []
    # Finds the header that says "Directs" and looks for the data right after it
    directs_header = soup.find(lambda tag: tag.name in ['h2', 'h3', 'div'] and 'Directs' in tag.text)
    
    if directs_header:
        # Grabs the container right after the Directs header
        matches_container = directs_header.find_next('div')
        if matches_container:
            # Looks for individual match text blocks (e.g., "Terminé MS 0 EMM 0")
            for match_text in matches_container.stripped_strings:
                if len(match_text) > 5: # basic filter to catch match lines
                    live_matches.append({"match_info": match_text})
                    
    if live_matches:
        db.collection('sports_data').document('live_scores').set({"matches": live_matches})
        print("Live scores updated successfully!")

    print("Scrape run finished.")

else:
    print(f"Failed to load Kawarji. Status Code: {response.status_code}")
