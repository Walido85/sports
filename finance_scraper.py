import cloudscraper
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account
import requests
import os
import json
import time

# === FIRESTORE CONFIG ===
firebase_secret = os.environ.get('FIREBASE_SERVICE_ACCOUNT')
if not firebase_secret:
    print("No credentials.")
    exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(
    project='tunisia-radios-d7aa8',
    credentials=credentials,
    database='(default)'
)
print("✅ Connected to Firestore (default database)")

scraper = cloudscraper.create_scraper(
    browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
)


def scrape_tunisia_stocks():
    url = 'https://www.african-markets.com/en/stock-markets/bvmt/listed-companies?hl=en-US'
    print("Scraping BVMT stocks...")
    time.sleep(2)
    r = scraper.get(url, timeout=20)
    if r.status_code != 200:
        print(f"⚠️ Blocked ({r.status_code})")
        return

    soup = BeautifulSoup(r.content, 'html.parser')
    stocks = []
    table = soup.find('table')
    if table:
        for row in table.find_all('tr')[1:]:
            cells = row.find_all('td')
            if len(cells) >= 4:
                name = cells[0].get_text(strip=True)
                last = cells[1].get_text(strip=True)
                change_pct = cells[2].get_text(strip=True)
                date = cells[3].get_text(strip=True) if len(cells) > 3 else ""
                if name and last:
                    stocks.append({
                        "name": name,
                        "last": last,
                        "change_pct": change_pct,
                        "date": date
                    })

    if stocks:
        db.collection('finance').document('tunisia_stocks').set({
            "stocks": stocks[:80],
            "source": "african-markets.com/listed-companies",
            "last_updated": "now",
            "total": len(stocks)
        })
        print(f"✅ Saved {len(stocks)} BVMT stocks")
    else:
        print("⚠️ No table found")


def scrape_tunisia_exchange_rates():
    print("Fetching TND exchange rates...")
    url = 'https://open.er-api.com/v6/latest/TND'
    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        print(f"⚠️ Exchange rate API failed ({r.status_code})")
        return

    data = r.json()
    raw = data.get('rates', {})

    currencies = ['EUR', 'USD', 'GBP', 'CAD']
    rates = []
    for currency in currencies:
        if currency in raw:
            value = round(1 / raw[currency], 4)
            rates.append({"currency": currency, "value": str(value)})

    db.collection('finance').document('exchange_rates').set({
        "tnd_rates": rates,
        "source": "open.er-api.com",
        "date": data.get('time_last_update_utc', '')
    })
    print(f"✅ Saved {len(rates)} live exchange rates")


def scrape_international_indices():
    print("Scraping international indices...")
    url = 'https://finance.yahoo.com/world-indices'
    r = scraper.get(url, timeout=15)
    if r.status_code != 200:
        print(f"⚠️ Yahoo blocked ({r.status_code})")
        return

    soup = BeautifulSoup(r.content, 'html.parser')
    indices = []
    rows = soup.find_all('tr')
    for row in rows[1:]:
        cells = row.find_all('td')
        if len(cells) >= 4:
            indices.append({
                "name": cells[0].get_text(strip=True),
                "last": cells[1].get_text(strip=True),
                "chg": cells[2].get_text(strip=True),
                "chg_pct": cells[3].get_text(strip=True),
            })

    if indices:
        db.collection('finance').document('international_indices').set({
            "indices": indices[:20]
        })
        print(f"✅ Saved {len(indices)} international indices")
    else:
        print("⚠️ No indices found")


# === RUN ===
scrape_tunisia_exchange_rates()
scrape_tunisia_stocks()
scrape_international_indices()
