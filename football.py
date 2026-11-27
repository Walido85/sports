import asyncio
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

from playwright.async_api import async_playwright
from playwright_stealth import Stealth

sys.stdout.reconfigure(line_buffering=True)

HISTORY_URL = "https://raw.githubusercontent.com/Walido85/sports/data/history.json"
DETAILS_URL = "https://raw.githubusercontent.com/Walido85/sports/data/match_details.json"
LIVE_API_URL = "https://prod-cdn-public-api.livescore.com/v1/api/app/live/soccer/0?countryCode=TN&locale=en"
DATE_API_URL = "https://prod-cdn-public-api.livescore.com/v1/api/app/date/soccer/{ymd}/0?countryCode=TN&locale=en"
LOGO_CDN_PREFIX = "https://lsm-static-prod.livescore.com/medium/"

DATE_WINDOW_PAST_DAYS = 2
DATE_WINDOW_FUTURE_DAYS = 14
API_CONCURRENCY = 6
MAX_DETAIL_FETCHES_PER_RUN = 20

LEAGUES = [
    {"slug": "tunisia-ligue-1",       "name": "Tunisia Ligue 1",      "url": "https://www.livescore.com/en/football/tunisia/ligue-i/"},
    {"slug": "premier-league",        "name": "Premier League",        "url": "https://www.livescore.com/en/football/england/premier-league/"},
    {"slug": "laliga",                "name": "LaLiga",                "url": "https://www.livescore.com/en/football/spain/laliga/"},
    {"slug": "serie-a",               "name": "Serie A",               "url": "https://www.livescore.com/en/football/italy/serie-a/"},
    {"slug": "bundesliga",            "name": "Bundesliga",            "url": "https://www.livescore.com/en/football/germany/bundesliga/"},
    {"slug": "ligue-1",               "name": "Ligue 1",               "url": "https://www.livescore.com/en/football/france/ligue-1/"},
    {"slug": "uefa-champions-league", "name": "UEFA Champions League", "url": "
