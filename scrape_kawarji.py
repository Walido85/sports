import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account
import os
import json

# --- CONNECT TO FIRESTORE ---
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
print("✅ Connected to Firestore (walid database)")

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

def scrape_matches(url, results_doc, fixtures_doc):
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed: {url} ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    results = []
    fixtures = []
    for item in soup.find_all(class_='match-item'):
        h5_teams = item.find_all('h5')
        team_links = item.find_all('a', href=lambda h: h and '/equipe/' in h)
        teams = []
        if len(h5_teams) >= 2:
            teams = [h5_teams[0].get_text(strip=True), h5_teams[1].get_text(strip=True)]
        elif len(team_links) >= 2:
            teams = [team_links[0].get_text(strip=True), team_links[1].get_text(strip=True)]
        if len(teams) < 2:
            continue
        score_link = item.find('a', href=lambda h: h and '/rencontre/' in h)
        text_lines = [t.strip() for t in item.stripped_strings if t.strip()]
        date_text = text_lines[0] if text_lines else ''
        if score_link:
            score = score_link.get_text(strip=True)
            results.append({"date": date_text, "home": teams[0], "score": score, "away": teams[1]})
        else:
            fixtures.append({"date": date_text, "home": teams[0], "away": teams[1]})

    if results:
        db.collection('leagues').document(results_doc).set({"matches": results})
        print(f"✅ Saved {len(results)} results → {results_doc}")
    if fixtures:
        db.collection('leagues').document(fixtures_doc).set({"matches": fixtures})
        print(f"✅ Saved {len(fixtures)} fixtures → {fixtures_doc}")

def scrape_standings(url, doc_name):
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed: {url} ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    standings = []
    for ul in soup.find_all('ul'):
        valid_rows = []
        for li in ul.find_all('li', recursive=False):
            parts = [t.strip() for t in li.stripped_strings if t.strip()]
            if len(parts) >= 10 and parts[0].isdigit() and int(parts[0]) <= 30:
                valid_rows.append({
                    "position": parts[0], "team": parts[1], "played": parts[2],
                    "wins": parts[3], "draws": parts[4], "losses": parts[5],
                    "goals_for": parts[6], "goals_against": parts[7],
                    "goal_diff": parts[8], "points": parts[9]
                })
        if len(valid_rows) >= 5:
            standings = valid_rows
            break
    if standings:
        db.collection('leagues').document(doc_name).set({"table": standings})
        print(f"✅ Saved {len(standings)} standings → {doc_name}")

def scrape_live():
    r = requests.get('https://live.kawarji.com/', headers=headers)
    if r.status_code != 200:
        print(f"Failed live ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    live_data = []
    for h1 in soup.find_all(['h1', 'h2']):
        comp_name = h1.get_text(strip=True)
        matches = []
        for sibling in h1.find_next_siblings():
            if sibling.name in ('h1', 'h2'):
                break
            sib_text = sibling.get_text('|', strip=True)
            if sib_text and
