import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account
import os
import json

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

def scrape_matches(url, results_doc, fixtures_doc):
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed: {url} ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    results = []
    fixtures = []
    for item in soup.find_all('li', class_='match-item'):
        h5_teams = item.find_all('h5')
        score_link = item.find('a', href=lambda h: h and '/rencontre/' in h)
        text_lines = [t.strip() for t in item.stripped_strings if t.strip()]
        date_text = text_lines[0] if text_lines else ''

        if len(h5_teams) >= 2:
            home = h5_teams[0].get_text(strip=True)
            away = h5_teams[1].get_text(strip=True)
            if score_link:
                score = score_link.get_text(strip=True)
                results.append({
                    "date": date_text, "home": home,
                    "score": score, "away": away
                })
            else:
                fixtures.append({
                    "date": date_text, "home": home, "away": away
                })

    if results:
        db.collection('leagues').document(results_doc).set({"matches": results})
        print(f"Saved {len(results)} results -> {results_doc}")
    else:
        print(f"No results for {results_doc}")

    if fixtures:
        db.collection('leagues').document(fixtures_doc).set({"matches": fixtures})
        print(f"Saved {len(fixtures)} fixtures -> {fixtures_doc}")
    else:
        print(f"No fixtures for {fixtures_doc}")

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
                    "position": parts[0],
                    "team": parts[1],
                    "played": parts[2],
                    "wins": parts[3],
                    "draws": parts[4],
                    "losses": parts[5],
                    "goals_for": parts[6],
                    "goals_against": parts[7],
                    "goal_diff": parts[8],
                    "points": parts[9]
                })
        if len(valid_rows) >= 5:
            standings = valid_rows
            break

    if standings:
        db.collection('leagues').document(doc_name).set({"table": standings})
        print(f"Saved {len(standings)} standings -> {doc_name}")
    else:
        print(f"No standings for {doc_name}")

def scrape_live():
    r = requests.get('https://live.kawarji.com/', headers=headers)
    if r.status_code != 200:
        print(f"Failed live ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    sections = []
    current_section = None
    for el in soup.find_all(['h1', 'h2', 'h3', 'div', 'section', 'article']):
        if el.name in ('h1', 'h2'):
            if current_section and current_section.get('matches'):
                sections.append(current_section)
            current_section = {"competition": el.get_text(strip=True), "matches": []}

    # Simpler approach: get all text blocks split by competition
    text = soup.get_text('\n', strip=True)
    lines = [l for l in text.split('\n') if l.strip()]

    competitions = []
    current = None
    matches_buffer = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # Competition headers usually contain ":" and key words
        if any(x in line for x in ['Ligue', 'Coupe', 'Championnat', 'journée', 'Premier', 'Liga', 'Serie', 'Bundesliga', 'Finale', 'Demi']) and len(line) < 100 and ':' in line:
            if current:
                competitions.append(current)
            current = {"competition": line, "matches": []}
        i += 1

    # Direct extraction from live data structure
    live_data = []
    # Each match in live page has team, score, team pattern
    for h1 in soup.find_all(['h1', 'h2']):
        comp_name = h1.get_text(strip=True)
        # Find next siblings until next h1/h2
        matches = []
        for sibling in h1.find_next_siblings():
            if sibling.name in ('h1', 'h2'):
                break
            sib_text = sibling.get_text('|', strip=True)
            if sib_text and len(sib_text) > 5:
                matches.append(sib_text[:300])
        if matches:
            live_data.append({"competition": comp_name, "raw": matches[:20]})

    if live_data:
        db.collection('leagues').document('live_scores').set({"sections": live_data})
        print(f"Saved {len(live_data)} live sections")
    else:
        print("No live data")


# --- TUNISIA ---
scrape_matches('https://www.kawarji.com/resultats/ligue1/2025-2026', 'results_ligue1_tunisia', 'fixtures_ligue1_tunisia')
scrape_standings('https://www.kawarji.com/classement/ligue1/2025-2026', 'standings_ligue1_tunisia')

scrape_matches('https://www.kawarji.com/resultats/ligue2GrA/2025-2026', 'results_ligue2_groupeA', 'fixtures_ligue2_groupeA')
scrape_standings('https://www.kawarji.com/classement/ligue2GrA/2025-2026', 'standings_ligue2_groupeA')

scrape_matches('https://www.kawarji.com/resultats/ligue2GrB/2025-2026', 'results_ligue2_groupeB', 'fixtures_ligue2_groupeB')
scrape_standings('https://www.kawarji.com/classement/ligue2GrB/2025-2026', 'standings_ligue2_groupeB')

# --- EUROPE ---
scrape_matches('https://www.kawarji.com/resultats/laliga/2025-2026', 'results_la_liga', 'fixtures_la_liga')
scrape_standings('https://www.kawarji.com/classement/laliga/2025-2026', 'standings_la_liga')

scrape_matches('https://www.kawarji.com/resultats/premier-league/2025-2026', 'results_premier_league', 'fixtures_premier_league')
scrape_standings('https://www.kawarji.com/classement/premier-league/2025-2026', 'standings_premier_league')

scrape_matches('https://www.kawarji.com/resultats/serie-a/2025-2026', 'results_serie_a', 'fixtures_serie_a')
scrape_standings('https://www.kawarji.com/classement/serie-a/2025-2026', 'standings_serie_a')

scrape_matches('https://www.kawarji.com/resultats/ligue1fr/2025-2026', 'results_ligue1_france', 'fixtures_ligue1_france')
scrape_standings('https://www.kawarji.com/classement/ligue1fr/2025-2026', 'standings_ligue1_france')

scrape_matches('https://www.kawarji.com/resultats/bundesliga/2025-2026', 'results_bundesliga', 'fixtures_bundesliga')
scrape_standings('https://www.kawarji.com/classement/bundesliga/2025-2026', 'standings_bundesliga')

# --- LIVE ---
scrape_live()

print("Done.")
