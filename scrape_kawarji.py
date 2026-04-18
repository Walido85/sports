import requests
from bs4 import BeautifulSoup
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
from datetime import datetime

# --- 1. INITIALIZE FIREBASE ---
# Using the same logic as your Node.js cert(serviceAccount)
firebase_secret = os.environ.get('FIREBASE_CREDENTIALS')
if not firebase_secret:
    print("Error: FIREBASE_CREDENTIALS not found.")
    exit(1)

cred_dict = json.loads(firebase_secret)
cred = credentials.Certificate(cred_dict)

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'projectId': 'tunisia-radios-d7aa8'
    })

# Targeting your 'walid' database
db = firestore.client(database_id='walid')

async def run_scraper():
    try:
        print("Starting scrape...")
        
        # Using the Ligue 1 URL from your previous message
        url = "https://www.kawarji.com/resultats/ligue1/2025-2026/25"
        
        # Using the same headers logic as your axios call
        headers = { "User-Agent": "Mozilla/5.0" }
        response = requests.get(url, headers=headers, timeout=20)
        
        # Cheerio equivalent in Python is BeautifulSoup
        soup = BeautifulSoup(response.content, 'html.parser')

        standings = []
        
        # --- MATCHING YOUR LOGIC EXACTLY ---
        # $('table.table-classement tr').each...
        # Note: If Kawarji uses a different class on the results page, 
        # we target 'table' directly to be safe, just like your loop.
        table = soup.find('table', class_='table-classement') or soup.find('table')
        
        if table:
            rows = table.find_all('tr')
            for i, el in enumerate(rows):
                if i == 0: continue  # Skip header row
                
                cols = el.find_all('td')
                if len(cols) >= 6:
                    standings.append({
                        "rank": cols[0].get_text(strip=True),
                        "team": cols[1].get_text(strip=True),
                        "played": cols[2].get_text(strip=True),
                        "gd": cols[4].get_text(strip=True), # nth-child(5)
                        "points": cols[5].get_text(strip=True) # nth-child(6)
                    })

        # --- PREPARE DATA ---
        data_to_save = {
            "lastUpdated": datetime.utcnow().isoformat(),
            "standings": standings,
            "matches": [] # Keeping your structure
        }

        # --- WRITE TO FIRESTORE ---
        print("Writing to Firestore...")
        # Saving to the same collection structure you used
        db.collection('sports_data').document('ligue-1').set(data_to_save)

        print(f"Scrape and write completed successfully! Saved {len(standings)} teams.")

    except Exception as e:
        print(f"Error during scraping: {e}")
        exit(1)

# Execute
import asyncio
if __name__ == "__main__":
    asyncio.run(run_scraper())
