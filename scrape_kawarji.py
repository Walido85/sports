import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json

firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if firebase_secret:
    cred_dict = json.loads(firebase_secret)
    cred = credentials.Certificate(cred_dict)
    try:
        firebase_admin.initialize_app(cred)
    except ValueError:
        pass
    db = firestore.client(database='walid')
    print("Connected.")
else:
    print("No credentials.")
    exit(1)

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# --- RESULTS ---
r = requests.get('https://www.kawarji.com/resultats', headers=headers)
if r.status_code == 200:
    soup = BeautifulSoup(r.content, 'html.parser')
    matches = []
    for row in soup.find_all('tr'):
        cols = row.find_all('td')
        if len(cols) >= 3:
            matches.append({
                "home": cols[0].text.strip(),
                "score": cols[1].text.strip(),
                "away": cols[2].text.strip()
            })
    print(f"Results found: {len(matches)}")
    if matches:
        db.collection('leagues').document('results_ligue_1').set({"matches": matches})
        print("Results saved!")

# --- STANDINGS ---
r2 = requests.get('https://www.kawarji.com/classement', headers=headers)
if r2.status_code == 200:
    soup2 = BeautifulSoup(r2.content, 'html.parser')
    standings = []
    for row in soup2.find_all('tr')[1:]:
        cols = row.find_all('td')
        if len(cols) >= 4:
            standings.append({
                "position": cols[0].text.strip(),
                "team": cols[1].text.strip(),
                "played": cols[2].text.strip(),
                "points": cols[3].text.strip()
            })
    print(f"Standings found: {len(standings)}")
    if standings:
        db.collection('leagues').document('standings_ligue_1').set({"table": standings})
        print("Standings saved!")
