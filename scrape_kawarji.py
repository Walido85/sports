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

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
}

def scrape_tunisia_stocks():
    url = 'https://www.ilboursa.com/marches/aaz'
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        print(f"⚠️ ilboursa blocked ({r.status_code})")
        return
    
    soup = BeautifulSoup(r.content, 'html.parser')
    stocks = []
    table = soup.find('table')
    if table:
        for row in table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) >= 8:
                stocks.append({
                    "name": cells[0].get_text(strip=True),
                    "last": cells[6].get_text(strip=True),
                    "high": cells[2].get_text(strip=True),
                    "low": cells[3].get_text(strip=True),
                    "volume_shares": cells[4].get_text(strip=True),
                    "volume_value": cells[5].get_text(strip=True),
                    "change_pct": cells[7].get_text(strip=True),
                })
    
    if stocks:
        db.collection('finance').document('tunisia_stocks').set({
            "stocks": stocks[:80],
            "source": "ilboursa.com",
            "last_updated": "now"
        })
        print(f"✅ Saved {len(stocks)} fresh BVMT stocks from ilboursa")
    else:
        print("⚠️ No stock table found")

def scrape_tunisia_exchange_rates():
    # Using dinartunisien.com instead of BCT
    url = 'https://www.dinartunisien.com/en'
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        print(f"Failed dinartunisien ({r.status_code})")
        return
    
    soup = BeautifulSoup(r.content, 'html.parser')
    rates = []
    # Look for currency rows (EUR, USD, etc.)
    for row in soup.find_all('tr'):
        cells = row.find_all('td')
        if len(cells) >= 2:
            currency_text = cells[0].get_text(strip=True).upper()
            if any(c in currency_text for c in ['EUR', 'USD', 'GBP', 'CAD']):
                value = cells[1].get_text(strip=True) if len(cells) > 1 else ""
                rates.append({"currency": currency_text, "value": value})
    
    if rates:
        db.collection('finance').document('exchange_rates').set({
            "tnd_rates": rates,
            "source": "dinartunisien.com",
            "date": "latest"
        })
        print(f"✅ Saved {len(rates)} Tunisia exchange rates")
        for r in rates:
            print(f"   {r['currency']}: {r['value']}")
    else:
        print("⚠️ No exchange rates found on dinartunisien")

def scrape_international_indices():
    url = 'https://www.investing.com/indices/major-indices'
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code != 200:
        print(f"⚠️ investing.com blocked ({r.status_code})")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    indices = []
    rows = soup.find_all('tr')
    for row in rows[1:]:
        cells = row.find_all('td')
        if len(cells) < 6: continue
        indices.append({
            "name": cells[0].get_text(strip=True),
            "last": cells[1].get_text(strip=True),
            "high": cells[2].get_text(strip=True),
            "low": cells[3].get_text(strip=True),
            "chg": cells[4].get_text(strip=True),
            "chg_pct": cells[5].get_text(strip=True),
        })
    if indices:
        db.collection('finance').document('international_indices').set({"indices": indices})
        print(f"✅ Saved {len(indices)} international indices")
    else:
        print("No indices found")

print("🚀 Starting finance scraper (no BCT)...")
scrape_tunisia_stocks()
scrape_tunisia_exchange_rates()
scrape_international_indices()
print("🎉 Finance scraper finished!")
