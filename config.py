"""
Configuration - edit ONLY these fields for each new brand.
How it works automatically:
  1. If APP_STORE_ID is set -> scrapes Apple App Store reviews
  2. If APP_STORE_ID is empty -> scrapes Google Reviews via SerpAPI
  3. GitHub Actions runs this on every push to config.py
"""

# ── Brand Settings (only thing you change) ────────────────────────────────────
BRAND_NAME   = "MTA"
APP_NAME     = BRAND_NAME
# NOTE: KEYWORDS feeds the Google Maps/SerpAPI scraper, which loops every
# keyword across all 50 US states - built for nationwide retail chains.
# MTA is a single-region transit agency, so that nationwide loop doesn't fit.
# Leave SERPAPI_KEY unset (see .env.example) to skip it entirely and run on
# App Store reviews only. KEYWORDS is left populated in case you later adapt
# the scraper for borough/station-level search instead of nationwide states.
KEYWORDS     = ["MTA subway station", "MTA bus stop", "NYC transit"]

# ── App Store (leave blank if no app) ────────────────────────────────────────
APP_STORE_ID = "1297605670"   # The Official MTA App
APP_COUNTRY  = "us"

# ── Platform Branding ─────────────────────────────────────────────────────────
PLATFORM_TITLE    = "MTA Customer Intelligence Platform"
PLATFORM_SUBTITLE = "Rider Experience & Service Insights"
PLATFORM_ICON     = "🚇"

# ── AI Model ──────────────────────────────────────────────────────────────────
GROQ_MODEL = "llama-3.3-70b-versatile"

# ── Scraper Settings ──────────────────────────────────────────────────────────
MAX_REVIEW_PAGES = 10

# ── Data Paths ────────────────────────────────────────────────────────────────
DATA_DIR       = "data"
REVIEWS_CSV    = "data/reviews.csv"
BUSINESSES_CSV = "data/businesses.csv"

# ── Analytics Settings ────────────────────────────────────────────────────────
ANOMALY_THRESHOLD_STARS = 0.4
SIGNIFICANT_DELTA_STARS = 0.3
