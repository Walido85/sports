import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

# --- 1. CONNECTION ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
cred_dict = json.loads(firebase_secret)
cred = credentials.Certificate(cred_dict)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {'projectId': 'tunisia-radios-d7aa8'})

db = firestore.client(database_id='walid')

# --- 2. TARGETED SCRAPE ---
URL = 'https://www.kawarji.com/resultats/ligue1/2025-2026/25'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
}

def scrape():
    res = requests.get(URL, headers=HEADERS, timeout=20)
    print(f"Status Code: {res.status_code}")
    
    # Debug: see what the site is sending back
    if "forbidden" in res.text.lower() or "captcha" in res.text.lower():
        print("Blocked by security. Retrying with session...")
        return [], []

    soup = BeautifulSoup(res.content, 'html.parser')
    
    standings = []
    matches = []

    # --- STANDINGS ---
    # Look for the table with ranking data
    table = soup.find('table') 
    if table:
        for row in table.find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) >= 4:
                standings.append({
                    "rank": cols[0].get_text(strip=True),
                    "team": cols[1].get_text(strip=True),
                    "played": cols[2].get_text(strip=True),
                    "pts": cols[3].get_text(strip=True)
                })

    # --- MATCHES ---
    # Based on the screenshot: Teams are in cols, score is in the middle
    # We look for the "row" containers specifically in the results section
    for row in soup.find_all('div', class_='row'):
        cells = row.find_all('div')
        # On this specific page, Kawarji uses a 3-column layout for scores
        if len(cells) >= 3:
            t1 = cells[0].get_text(strip=True)
            score = cells[1].get_text(strip=True)
            t2 = cells[2].get_text(strip=True)
            
            # Filter: Must look like a score (e.g. 1-0 or 0-1)
            if '-' in score and len(score) <= 5:
                matches.append({"home": t1, "away": t2, "score": score})

    return standings, matches

# --- 3. UPLOAD ---
standings_data, matches_data = scrape()

if standings_data:
    db.collection('leagues').document('tunisia_ligue_1').set({
        "table": standings_data,
        "updated": firestore.SERVER_TIMESTAMP
    })
    print(f"Standings updated: {len(standings_data)} teams")

if matches_data:
    db.collection('leagues').document('fixtures_results').set({
        "matches": matches_data,
        "updated": firestore.SERVER_TIMESTAMP
    })
    print(f"Matches updated: {len(matches_data)} results")

if not standings_data and not matches_data:
    print("CRITICAL: Scraper returned zero data.")
