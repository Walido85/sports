import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account
import os
import json
import time

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

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
}

def scrape_tunisia_stocks():
    url = 'https://ati.attijaribourse.com.tn/AttijariBourse/marche'
    print("Scraping BVMT stocks from Attijari Bourse...")
    time.sleep(2)
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code != 200:
        print(f"⚠️ Attijari blocked ({r.status_code})")
        return
    
    soup = BeautifulSoup(r.content, 'html.parser')
    stocks = []
    table = soup.find('table')
    if table:
        for row in table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) >= 8:
                name = cells[0].get_text(strip=True).split('(')[0].strip()
                last = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                change_pct = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                if name and last:
                    stocks.append({
                        "name": name,
                        "last": last,
                        "change_pct": change_pct,
                    })
    
    if stocks:
        db.collection('finance').document('tunisia_stocks').set({
            "stocks": stocks[:100],
            "source": "ati.attijaribourse.com.tn",
            "last_updated": "now",
            "total": len(stocks)
        })
        print(f"✅ Saved {len(stocks)} BVMT stocks from Attijari Bourse")
    else:
        print("⚠️ No table found on Attijari Bourse")

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

print("🚀 Starting finance scraper with Attijari Bourse...")
scrape_tunisia_stocks()
scrape_tunisia_exchange_rates()
scrape_international_indices()
print("🎉 Finance scraper finished!")
