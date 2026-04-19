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
    print("Trying to scrape pharmacies with dropdown simulation...")

    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    # First load the page
    r = requests.get(url, headers=headers, timeout=20, verify=False)
    if r.status_code != 200:
        print(f"Failed to load page ({r.status_code})")
        return

    soup = BeautifulSoup(r.content, 'html.parser')
    pharmacies = []

    # Try to find any pharmacy list (table or divs)
    table = soup.find('table')
    if table:
        print("Found table - parsing...")
        for row in table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) >= 4:
                pharmacies.append({
                    "name": cells[0].get_text(strip=True),
                    "type": cells[1].get_text(strip=True),   # Officine, Garde (night), etc.
                    "governorate": cells[2].get_text(strip=True),
                    "city": cells[3].get_text(strip=True),
                    "address": cells[4].get_text(strip=True) if len(cells) > 4 else "",
                    "phone": cells[5].get_text(strip=True) if len(cells) > 5 else "",
                })
    else:
        print("No table found - looking for divs...")
        # Fallback for div-based layout
        for item in soup.find_all(['div', 'li'], class_=lambda x: x and ('pharmacie' in str(x).lower() or 'officine' in str(x).lower())):
            name_tag = item.find(['h3', 'h4', 'strong', 'a'])
            name = name_tag.get_text(strip=True) if name_tag else "Unknown"
            pharmacies.append({
                "name": name,
                "type": "Officine / Garde",
                "governorate": "",
                "city": "",
                "address": "",
                "phone": ""
            })

    if pharmacies:
        db.collection('pharmacies').document('all_pharmacies').set({
            "pharmacies": pharmacies,
            "total": len(pharmacies),
            "source": "dpm.tn",
            "last_updated": "now",
            "note": "Morning + Night pharmacies (garde)"
        })
        print(f"✅ Saved {len(pharmacies)} Tunisian pharmacies")
    else:
        print("⚠️ Still no pharmacies found. The page is heavily dynamic with dropdowns and JavaScript.")

print("🚀 Starting Pharmacies Scraper (dropdown attempt)...")
scrape_pharmacies()
print("🎉 Pharmacies scraper finished!")
