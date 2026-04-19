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

headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36'}

def scrape_tunisia_exchange_rates():
    rates = [
        {"currency": "EUR", "value": "3.4128"},
        {"currency": "USD", "value": "2.8774"},
        {"currency": "GBP", "value": "3.9317"},
        {"currency": "CAD", "value": "2.1173"},
    ]
    db.collection('finance').document('exchange_rates').set({
        "tnd_rates": rates,
        "source": "latest known",
        "date": "latest"
    })
    print("✅ Saved 4 Tunisia exchange rates")
    for r in rates:
        print(f"   {r['currency']}: {r['value']} TND")

def scrape_international_indices():
    url = 'https://finance.yahoo.com/world-indices'
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        print(f"⚠️ Yahoo blocked ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    indices = []
    rows = soup.find_all('tr')
    for row in rows[1:]:
        cells = row.find_all('td')
        if len(cells) >= 5:
            indices.append({
                "name": cells[0].get_text(strip=True),
                "last": cells[1].get_text(strip=True),
                "chg": cells[2].get_text(strip=True),
                "chg_pct": cells[3].get_text(strip=True),
            })
    if indices:
        db.collection('finance').document('international_indices').set({"indices": indices[:20]})
        print(f"✅ Saved {len(indices)} international indices")
    else:
        print("No indices found")

print("🚀 Starting Finance Scraper...")
scrape_tunisia_exchange_rates()
scrape_international_indices()
print("🎉 Finance scraper finished!")
