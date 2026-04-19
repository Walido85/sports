import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account
import os
import json

# === SAME FIRESTORE CONFIG ===
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

def scrape_pharmacies():
    url = 'https://dpm.tn/pharmacie/liste-des-officines'
    print("Scraping all Tunisian pharmacies from official DPM site...")
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code != 200:
        print(f"Failed to load page ({r.status_code})")
        return

    soup = BeautifulSoup(r.content, 'html.parser')
    pharmacies = []

    # The page uses a table or list of pharmacies
    table = soup.find('table')
    if table:
        for row in table.find_all('tr')[1:]:   # skip header
            cells = row.find_all('td')
            if len(cells) >= 4:
                pharmacies.append({
                    "name": cells[0].get_text(strip=True),
                    "type": cells[1].get_text(strip=True) if len(cells) > 1 else "",   # Officine, Hospitalière, Nuit, etc.
                    "address": cells[2].get_text(strip=True) if len(cells) > 2 else "",
                    "phone": cells[3].get_text(strip=True) if len(cells) > 3 else "",
                    "governorate": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                    "city": cells[5].get_text(strip=True) if len(cells) > 5 else "",
                })
    else:
        # Fallback: look for divs with pharmacy info
        for item in soup.find_all('div', class_=lambda x: x and 'pharmacy' in x.lower()):
            name = item.find('h3') or item.find('h4') or item.find('strong')
            name = name.get_text(strip=True) if name else "Unknown"
            pharmacies.append({"name": name, "type": "Officine", "address": "", "phone": ""})

    if pharmacies:
        db.collection('pharmacies').document('all_pharmacies').set({
            "pharmacies": pharmacies,
            "total": len(pharmacies),
            "source": "dpm.tn",
            "last_updated": "now",
            "types_included": "all (Officine, Hospitalière, Nuit, etc.)"
        })
        print(f"✅ Saved {len(pharmacies)} Tunisian pharmacies (all types)")
    else:
        print("⚠️ No pharmacies found on the page (may require JS or filters)")

print("🚀 Starting Pharmacies Scraper...")
scrape_pharmacies()
print("🎉 Pharmacies scraper finished! Data saved in 'pharmacies' collection")
