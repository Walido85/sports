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
    print(f"Project ID from secret: {cred_dict.get('project_id')}")
    print(f"Client email from secret: {cred_dict.get('client_email')}")
    cred = credentials.Certificate(cred_dict)
    
    try:
        firebase_admin.initialize_app(cred)
    except ValueError:
        pass
        
    db = firestore.client()
    print("Connected to Firestore successfully.")
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
    table = soup.find(lambda tag: tag.name == 'table' and 'équipe' in tag.text.lower())
    
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
            db.collection('leagues').document('standings_ligue_1').set({"table": standings})
            print("Standings saved!")

    # --- 4. SMART SCRAPE LIVE SCORES ---
    live_matches = []
    directs_header = soup.find(lambda tag: tag.name in ['h2', 'h3', 'div'] and 'Directs' in tag.text)
    
    if directs_header:
        container = directs_header.find_next('div')
        if container:
            for item in container.stripped_strings:
                if len(item) > 5:
                    live_matches.append({"info": item})
                    
    if live_matches:
        db.collection('leagues').document('live_scores').set({"matches": live_matches})
        print("Live scores saved!")

    print("Scrape process complete.")
else:
    print(f"Failed. Status: {response.status_code}")
