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

def scrape_results(url, doc_name):
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed: {url} ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    matches = []
    for item in soup.find_all(class_='match-item'):
        # Score is in <a href="/rencontre/...">
        score_link = item.find('a', href=lambda h: h and '/rencontre/' in h)
        # Teams are in <a href="/equipe/...">
        team_links = item.find_all('a', href=lambda h: h and '/equipe/' in h)
        # Date is plain text in the item
        text_lines = [t.strip() for t in item.stripped_strings]
        date_text = text_lines[0] if text_lines else ''
        
        if len(team_links) >= 2:
            home = team_links[0].get_text(strip=True)
            away = team_links[1].get_text(strip=True)
            score = score_link.get_text(strip=True) if score_link else '-'
            matches.append({
                "date": date_text,
                "home": home,
                "score": score,
                "away": away
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
