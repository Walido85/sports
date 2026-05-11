import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone

from playwright.async_api import async_playwright
from playwright_stealth import Stealth
from google.cloud import firestore
from google.oauth2 import service_account

sys.stdout.reconfigure(line_buffering=True)

firebase_secret = os.environ.get("FIREBASE_CREDENTIALS")
if not firebase_secret:
    print("❌ No FIREBASE_CREDENTIALS found.")
    sys.exit(1)

cred_dict = json.loads(firebase_secret)
credentials = service_account.Credentials.from_service_account_info(cred_dict)
db = firestore.Client(project="tunisia-radios-d7aa8", credentials=credentials, database="(default)")
print("✅ Firestore connected")

LEAGUES = [
    {"name": "Tunisia Ligue 1", "url": "https://www.livescore.com/en/football/tunisia/ligue-i/"},
    {"name": "Premier League", "url": "https://www.livescore.com/en/football/england/premier-league/"},
    {"name": "LaLiga", "url": "https://www.livescore.com/en/football/spain/laliga/"},
    {"name": "Serie A", "url": "https://www.livescore.com/en/football/italy/serie-a/"},
    {"name": "Bundesliga", "url": "https://www.livescore.com/en/football/germany/bundesliga/"},
    {"name": "Ligue 1", "url": "https://www.livescore.com/en/football/france/ligue-1/"},
    {"name": "UEFA Champions League", "url": "https://www.livescore.com/en/football/champions-league/"},
    {"name": "CAF Champions League", "url": "https://www.livescore.com/en/football/caf-champions-league/"}
]

async def scrape_all_live(context):
    page = await context.new_page()
    print("▶ Scraping Global LIVE matches...")
    
    live_matches = []
    try:
        await page.goto("https://www.livescore.com/en/football/live/", wait_until="domcontentloaded", timeout=60000)
        
        try:
            await page.wait_for_selector('div[data-id*="_mtc-r"]', timeout=10000)
        except:
            print("ℹ️ No live matches at this exact moment.")

        live_matches = await page.evaluate('''() => {
            const matches = [];
            const rows = document.querySelectorAll('div[data-id*="_mtc-r"]');
            
            for (const row of rows) {
                const statusText = row.querySelector('span[data-id*="st-tm"]')?.innerText.trim() || "";
                
                if (statusText === "FT" || statusText.includes("Canc") || statusText.includes("Postp") || statusText.includes(":")) {
                    continue;
                }
                
                const homeName = row.querySelector('div[data-id*="hm-tm-nm"]')?.innerText.trim() || "";
                const awayName = row.querySelector('div[data-id*="aw-tm-nm"]')?.innerText.trim() || "";
                if (!homeName || !awayName) continue;

                const imgs = row.querySelectorAll('img');
                const homeLogo = imgs[0]?.src || "";
                const awayLogo = imgs[1]?.src || "";
                const hScore = row.querySelector('div[data-id*="hm-sc"]')?.innerText.tr
