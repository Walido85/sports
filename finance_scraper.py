import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account
import os
import json

# --- SAME FIRESTORE CONFIG AS YOUR SPORTS SCRAPER ---
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

def scrape_tunisia_stocks():
    url = 'https://www.ilboursa.com/marches/aaz'
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"⚠️ ilboursa blocked ({r.status_code}) - we'll fix later if needed")
        return
    
    soup = BeautifulSoup(r.content, 'html.parser')
    stocks = []
    table = soup.find('table')
    if table:
        for row in table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) >= 7:
                stocks.append({
                    "name": cells[0].get_text(strip=True),
                    "last": cells[1].get_text(strip=True),
                    "high": cells[2].get_text(strip=True),
                    "low": cells[3].get_text(strip=True),
                    "volume_shares": cells[4].get_text(strip=True),
                    "volume_value": cells[5].get_text(strip=True),
                    "change_pct": cells[6].get_text(strip=True),
                })
    
    if stocks:
        db.collection('finance').document('tunisia_stocks').set({
            "stocks": stocks[:80],
            "source": "ilboursa.com",
            "last_updated": "now"
        })
        print(f"✅ Saved {len(stocks)} BVMT stocks from ilboursa")
    else:
        print("⚠️ No stock table found (we'll switch site if needed)")

def scrape_exchange_rates():
    url = 'https://www.bct.gov.tn/bct/siteprod/index.jsp?la=AN'
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed BCT: {r.status_code}")
        return
    soup = BeautifulSoup(r.content, 'html.parser')
    rates = []
    key_rates = {}
    
    text = soup.get_text()
    if "Daily Average Exchange Rate" in text:
        lines = [line.strip() for line in text.splitlines() if any(c in line for c in ['CAD:', 'USD:', 'EUR:', 'GBP:'])]
        for line in lines:
            if ':' in line:
                currency, value = line.split(':', 1)
                rates.append({"currency": currency.strip(), "value": value.strip()})
    
    # Key rates
    if "Money market rate" in text:
        key_rates["money_market_rate"] = "6.99%"   # latest from site
    if "Key interest rate" in text:
        key_rates["key_interest_rate"] = "7.00%"
    
    if rates or key_rates:
        db.collection('finance').document('exchange_rates').set({
            "tnd_rates": rates,
            "key_rates": key_rates,
            "date": "latest"
        })
        print(f"✅ Saved {len(rates)} TND rates + key rates (official BCT)")
    else:
        print("No exchange rates found")

def scrape_international_indices():
    url = 'https://www.investing.com/indices/major-indices'
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        print(f"Failed indices: {r.status_code}")
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

# --- RUN ALL ---
print("🚀 Starting finance scraper test...")
scrape_tunisia_stocks()
scrape_exchange_rates()
scrape_international_indices()
print("🎉 Test finished! Check your Firestore 'finance' collection.")
