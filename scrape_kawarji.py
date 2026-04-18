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

def scrape_league(url, doc_results, doc_standings):
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed: {url} ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')

    # --- RESULTS ---
    matches = []
    for item in soup.find_all('div', class_='match-item'):
        parts = item.find_all('div')
        text = item.get_text(separator='|').strip()
        # Extract home, score, away
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
        db.collection('leagues').document(doc_results).set({"matches": matches})
        print(f"Saved {len(matches)} results → {doc_results}")
    else:
        print(f"No results found for {doc_results}")

    # --- STANDINGS ---
    standings = []
    tabs = soup.find_all('div', class_='tab-pane')
    for tab in tabs:
        rows = tab.find_all('tr')
        if rows:
            for row in rows[1:]:
                cols = row.find_all('td')
                if len(cols) >= 4:
                    standings.append({
                        "position": cols[0].get_text(strip=True),
                        "team": cols[1].get_text(strip=True),
                        "played": cols[2].get_text(strip=True),
                        "points": cols[3].get_text(strip=True)
                    })
            break
        # Try non-table standings
        text = tab.get_text(strip=True)
        if 'pts' in text and len(text) > 50:
            # Widget standings format: pos+abbr+team+j+pts
            pattern = r'(\d+)\s*([A-Z]{2,4})\s*(.+?)\s*(\d+)\s*(\d+)'
            for m in re.finditer(pattern, text):
                standings.append({
                    "position": m.group(1),
                    "team": m.group(3).strip(),
                    "played": m.group(4),
                    "points": m.group(5)
                })
            if standings:
                break

    if standings:
        db.collection('leagues').document(doc_standings).set({"table": standings})
        print(f"Saved {len(standings)} standings → {doc_standings}")
    else:
        print(f"No standings found for {doc_standings}")


# --- SCRAPE ALL LEAGUES ---
scrape_league(
    'https://www.kawarji.com/resultats/',
    'results_ligue1_tunisia',
    'standings_ligue1_tunisia'
)

scrape_league(
    'https://www.kawarji.com/resultats-premier-league-angleterre/',
    'results_premier_league',
    'standings_premier_league'
)

scrape_league(
    'https://www.kawarji.com/resultats-liga-espagne/',
    'results_la_liga',
    'standings_la_liga'
)

scrape_league(
    'https://www.kawarji.com/resultats-serie-a-italie/',
    'results_serie_a',
    'standings_serie_a'
)

scrape_league(
    'https://www.kawarji.com/resultats-ligue-1-france/',
    'results_ligue1_france',
    'standings_ligue1_france'
)

scrape_league(
    'https://www.kawarji.com/resultats-bundesliga-allemagne/',
    'results_bundesliga',
    'standings_bundesliga'
)

print("Done.")
