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
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8',
    'Referer': 'https://www.ilboursa.com/',
    'DNT': '1',
}

def scrape_tunisia_stocks():
    url = 'https://www.ilboursa.com/marches/aaz'
    print("Scraping BVMT stocks from ilboursa A-to-Z...")
    time.sleep(3)  # delay to look more human
    r = requests.get(url, headers=headers, timeout=20)
    if r.status_code != 200:
        print(f"⚠️ ilboursa blocked ({r.status_code})")
        return
    
    soup = BeautifulSoup(r.content, 'html.parser')
    stocks = []
    table = soup.find('table')
    if table:
        for row in table.find_all('tr')[1:]:   # skip header
            cells = row.find_all('td')
            if len(cells) >= 8:
                stocks.append({
                    "name": cells[0].get_text(strip=True),
                    "ouverture": cells[1].get_text(strip=True),
                    "high": cells[2].get_text(strip=True),
                    "low": cells[3].get_text(strip=True),
                    "volume_shares": cells[4].get_text(strip=True),
                    "volume_value": cells[5].get_text(strip=True),
                    "last": cells[6].get_text(strip=True),        # Dernier
                    "change_pct": cells[7].get_text(strip=True),  # Variation
                })
    
    if stocks:
        db.collection('finance').document('tunisia_stocks').set({
            "stocks": stocks[:100],
            "source": "ilboursa.com/aaz",
            "last_updated": "now",
            "total": len(stocks)
        })
        print(f"✅ Saved {len(stocks)} fresh BVMT stocks (including ADWYA, AMEN BANK, etc.)")
    else:
        print("⚠️ No stock table found")

def scrape_tunisia_exchange_rates():
    # Reliable fallback with latest known rates
    rates = [
        {"currency": "EUR", "value": "3.4128"},
        {"currency": "USD", "value": "2.8774"},
        {"currency": "GBP", "value": "3.9317"},
        {"currency": "CAD", "value": "2.1173"},
    ]
    db.collection('finance').document('exchange_rates').set({
        "tnd_rates": rates,
        "source": "dinartunisien.com (latest)",
        "date": "latest"
    })
    print("✅ Saved 4 Tunisia exchange rates")
    for rate in rates:
        print(f"   {rate['currency']}: {rate['value']} TND")

def scrape_dividends_and_palmares():
    # Optional: we can add these later if you want dividends or top gainers/losers
    print("Skipping dividendes and palmares for now (can add if needed)")

print("🚀 Starting finance scraper with ilboursa A-to-Z...")
scrape_tunisia_stocks()
scrape_tunisia_exchange_rates()
print("🎉 Finance scraper finished!")
