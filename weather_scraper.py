import requests
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

def scrape_weather():
    print("🌤 Scraping full weather for 24 Tunisian cities + International...")

    # 24 Major Tunisian cities
    tunisian_cities = {
        "Tunis": "Tunis",
        "Sfax": "Sfax",
        "Sousse": "Sousse",
        "Kairouan": "Kairouan",
        "Bizerte": "Bizerte",
        "Gabes": "Gabes",
        "Gafsa": "Gafsa",
        "Ariana": "Ariana",
        "Ben Arous": "Ben+Arous",
        "La Marsa": "La+Marsa",
        "Hammamet": "Hammamet",
        "Monastir": "Monastir",
        "Mahdia": "Mahdia",
        "Nabeul": "Nabeul",
        "Kef": "Kef",
        "Jendouba": "Jendouba",
        "Beja": "Beja",
        "Siliana": "Siliana",
        "Zaghouan": "Zaghouan",
        "Tozeur": "Tozeur",
        "Kebili": "Kebili",
        "Medenine": "Medenine",
        "Tataouine": "Tataouine",
        "Tabarka": "Tabarka"
    }

    # International cities
    international_cities = {
        "Paris": "Paris",
        "London": "London",
        "New York": "New+York",
        "Dubai": "Dubai",
        "Istanbul": "Istanbul",
        "Mecca": "Mecca"
    }

    weather_data = {"tunisia": [], "international": [], "last_updated": "now"}

    # Tunisia cities
    for display_name, query in tunisian_cities.items():
        url = f"https://wttr.in/{query}?format=j1"
        try:
            r = requests.get(url, timeout=12)
            if r.status_code != 200:
                continue
            data = r.json()
            current = data['current_condition'][0]
            item = {
                "city": display_name,
                "temp_c": current['temp_C'],
                "feels_like_c": current['FeelsLikeC'],
                "weather_desc": current['weatherDesc'][0]['value'],
                "humidity": current['humidity'],
                "wind_kph": current['windspeedKmph']
            }
            weather_data["tunisia"].append(item)
        except:
            continue

    # International cities
    for display_name, query in international_cities.items():
        url = f"https://wttr.in/{query}?format=j1"
        try:
            r = requests.get(url, timeout=12)
            if r.status_code != 200:
                continue
            data = r.json()
            current = data['current_condition'][0]
            item = {
                "city": display_name,
                "temp_c": current['temp_C'],
                "feels_like_c": current['FeelsLikeC'],
                "weather_desc": current['weatherDesc'][0]['value'],
                "humidity": current['humidity'],
                "wind_kph": current['windspeedKmph']
            }
            weather_data["international"].append(item)
        except:
            continue

    # Save to Firestore
    db.collection('finance').document('weather').set(weather_data)
    print(f"✅ Saved weather for {len(weather_data['tunisia'])} Tunisian cities + {len(weather_data['international'])} international cities")

print("🚀 Starting Weather Scraper...")
scrape_weather()
print("🎉 Weather scraper finished! Data saved in finance/weather")
