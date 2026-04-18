import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account
import os
import json
import re

# --- CONNECT ---
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("No credentials.")
    exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(
    project='tunisia-radios-d7aa8',
    credentials=credentials,
    database='walid'
)
print("Connected.")

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def scrape_results(url, doc_name):
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed: {url} ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    matches = []
    for item in soup.find_all('div', class_='match-item'):
        home = item.find('div', class_=lambda c: c and 'home' in c)
        away = item.find('div', class_=lambda c: c and 'away' in c)
        score = item.find('div', class_=lambda c: c and 'score' in c)
        date_div = item.find('div', class_=lambda c: c and 'date' in c)

        home_text = home.get_text(strip=True) if home else ''
        away_text = away.get_text(strip=True) if away else ''
        score_text = score.get_text(strip=True) if score else '-'
        date_text = date_div.get_text(strip=True) if date_div else ''

        if home_text and away_text:
            matches.append({
                "date": date_text,
                "home": home_text,
                "score": score_text,
                "away": away_text
            })
    if matches:
        db.collection('leagues').document(doc_name).set({"matches": matches})
        print(f"Saved {len(matches)} results -> {doc_name}")
    else:
        print(f"No results for {doc_name}")

def scrape_standings(url, doc_name):
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed: {url} ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    standings = []
    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        if len(rows) > 5:
            for row in rows[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    standings.append({
                        "position": cols[0].get_text(strip=True),
                        "team": cols[1].get_text(strip=True),
                        "played": cols[2].get_text(strip=True),
                        "points": cols[-1].get_text(strip=True)
                    })
            if standings:
                break
    if standings:
        db.collection('leagues').document(doc_name).set({"table": standings})
        print(f"Saved {len(standings)} standings -> {doc_name}")
    else:
        print(f"No standings for {doc_name}")


# --- TUNISIA ---
scrape_results('https://www.kawarji.com/resultats/ligue1/2025-2026', 'results_ligue1_tunisia')
scrape_standings('https://www.kawarji.com/classement/ligue1/2025-2026', 'standings_ligue1_tunisia')

scrape_results('https://www.kawarji.com/resultats/ligue2GrA/2025-2026', 'results_ligue2_groupeA')
scrape_standings('https://www.kawarji.com/classement/ligue2GrA/2025-2026', 'standings_ligue2_groupeA')

scrape_results('https://www.kawarji.com/resultats/ligue2GrB/2025-2026', 'results_ligue2_groupeB')
scrape_standings('https://www.kawarji.com/classement/ligue2GrB/2025-2026', 'standings_ligue2_groupeB')

# --- EUROPE ---
scrape_results('https://www.kawarji.com/resultats/laliga/2025-2026', 'results_la_liga')
scrape_standings('https://www.kawarji.com/classement/laliga/2025-2026', 'standings_la_liga')

scrape_results('https://www.kawarji.com/resultats/premier-league/2025-2026', 'results_premier_league')
scrape_standings('https://www.kawarji.com/classement/premier-league/2025-2026', 'standings_premier_league')

scrape_results('https://www.kawarji.com/resultats/serie-a/2025-2026', 'results_serie_a')
scrape_standings('https://www.kawarji.com/classement/serie-a/2025-2026', 'standings_serie_a')

scrape_results('https://www.kawarji.com/resultats/ligue1fr/2025-2026', 'results_ligue1_france')
scrape_standings('https://www.kawarji.com/classement/ligue1fr/2025-2026', 'standings_ligue1_france')

scrape_results('https://www.kawarji.com/resultats/bundesliga/2025-2026', 'results_bundesliga')
scrape_standings('https://www.kawarji.com/classement/bundesliga/2025-2026', 'standings_bundesliga')

print("Done.")
