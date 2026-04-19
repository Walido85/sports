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

API_KEY = "5dce144e6323cd65714856c78e5196c2"

def scrape_weather():
    print("🌤 Scraping professional weather from OpenWeatherMap...")

    # 24 Tunisian cities
    tunisian_cities = {
        "Tunis": (36.8065, 10.1815),
        "Sfax": (34.7406, 10.7603),
        "Sousse": (35.8256, 10.6084),
        "Kairouan": (35.6781, 10.0963),
        "Bizerte": (37.2744, 9.8739),
        "Gabes": (33.8815, 10.0982),
        "Gafsa": (34.4250, 8.7842),
        "Ariana": (36.8667, 10.1667),
        "Ben Arous": (36.7531, 10.2189),
        "La Marsa": (36.8833, 10.3167),
        "Hammamet": (36.4000, 10.6167),
        "Monastir": (35.7833, 10.8333),
        "Mahdia": (35.5000, 11.0667),
        "Nabeul": (36.4500, 10.7333),
        "Kef": (36.1231, 8.7147),
        "Jendouba": (36.5000, 8.7833),
        "Beja": (36.7333, 9.1833),
        "Siliana": (36.0833, 9.3667),
        "Zaghouan": (36.4000, 10.1500),
        "Tozeur": (33.9167, 8.1333),
        "Kebili": (33.7000, 8.9667),
        "Medenine": (33.3500, 10.5000),
        "Tataouine": (32.9333, 10.4500),
        "Tabarka": (36.9500, 8.7667)
    }

    # International cities
    international_cities = {
        "Paris": (48.8566, 2.3522),
        "London": (51.5074, -0.1278),
        "New York": (40.7128, -74.0060),
        "Dubai": (25.2048, 55.2708),
        "Istanbul": (41.0082, 28.9784),
        "Mecca": (21.3891, 39.8579)
    }

    weather_data = {"tunisia": [], "international": [], "last_updated": "now", "source": "OpenWeatherMap"}

    # Tunisia
    for city_name, (lat, lon) in tunisian_cities.items():
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}&units=metric&lang=fr"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            weather_data["tunisia"].append({
                "city": city_name,
                "temp_c": round(data['main']['temp'], 1),
                "feels_like_c": round(data['main']['feels_like'], 1),
                "weather_desc": data['weather'][0]['description'],
                "humidity": data['main']['humidity'],
                "wind_kph": round(data['wind']['speed'] * 3.6, 1)
            })
        except:
            continue

    # International
    for city_name, (lat, lon) in international_cities.items():
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={API_KEY}&units=metric&lang=fr"
        try:
            r = requests.get(url, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            weather_data["international"].append({
                "city": city_name,
                "temp_c": round(data['main']['temp'], 1),
                "feels_like_c": round(data['main']['feels_like'], 1),
                "weather_desc": data['weather'][0]['description'],
                "humidity": data['main']['humidity'],
                "wind_kph": round(data['wind']['speed'] * 3.6, 1)
            })
        except:
            continue

    # Save
    db.collection('finance').document('weather').set(weather_data)
    print(f"✅ Saved weather for {len(weather_data['tunisia'])} Tunisian cities + {len(weather_data['international'])} international cities")
    print("Source: OpenWeatherMap (professional API)")

print("🚀 Starting Professional Weather Scraper...")
scrape_weather()
print("🎉 Weather scraper finished!")
