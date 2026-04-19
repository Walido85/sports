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
    print("Scraping ALL Tunisian pharmacies (Morning + Night/Garde)...")

    # Governorates / cities (from med.tn pattern)
    governorates = [
        "tunis", "sfax", "sousse", "kairouan", "bizerte", "gabes", "gafsa",
        "ariana", "ben-arous", "la-marsa", "hammamet", "monastir", "mahdia",
        "nabeul", "kef", "jendouba", "beja", "siliana", "zaghouan", "tozeur",
        "kebili", "medenine", "tataouine", "tabarka"
    ]

    all_pharmacies = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for gov in governorates:
        # Scrape morning pharmacies
        for typ in ["jour", "garde"]:
            url = f"https://www.med.tn/pharmacie/{typ}/{gov}"
            print(f"  → Checking {typ} pharmacies in {gov}...")

            try:
                r = requests.get(url, headers=headers, timeout=15, verify=False)
                if r.status_code != 200:
                    continue

                soup = BeautifulSoup(r.content, 'html.parser')
                items = soup.find_all(['div', 'li', 'tr'], class_=lambda x: x and ('pharmacie' in str(x).lower() or 'officine' in str(x).lower()))

                for item in items:
                    name_tag = item.find(['h3', 'h4', 'strong', 'a'])
                    if name_tag:
                        name = name_tag.get_text(strip=True)
                        all_pharmacies.append({
                            "name": name,
                            "type": "Morning (Jour)" if typ == "jour" else "Night (Garde)",
                            "governorate": gov.capitalize(),
                            "city": gov.capitalize(),
                            "address": "",
                            "phone": ""
                        })
            except:
                continue

    if all_pharmacies:
        db.collection('pharmacies').document('all_pharmacies').set({
            "pharmacies": all_pharmacies,
            "total": len(all_pharmacies),
            "source": "med.tn (jour + garde)",
            "last_updated": "now",
            "note": "All types: Morning pharmacies + Night (Garde) pharmacies, divided by governorate"
        })
        print(f"✅ Saved {len(all_pharmacies)} Tunisian pharmacies (Morning + Night/Garde)")
    else:
        print("⚠️ No pharmacies found (sites may block automated access)")

print("🚀 Starting Pharmacies Scraper (Morning + Night)...")
scrape_pharmacies()
print("🎉 Pharmacies scraper finished!")
