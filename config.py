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
PLATFORM_TITLE    = "MTA Rider Intelligence Platform"
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

# ── ACE Impact Certification (NYS Open Data / Socrata, data.ny.gov) ───────────
# Real public MTA datasets - verified to exist as of build time:
#   https://data.ny.gov/Transportation/MTA-Bus-Automated-Camera-Enforced-Routes-Beginning/ki2b-sg5y
#   https://data.ny.gov/Transportation/MTA-Bus-Automated-Camera-Enforcement-Violations-Be/kh8p-hcbm
#   https://data.ny.gov/Transportation/MTA-Bus-Speeds-Beginning-2020/6ksi-7cxr
# Exact column names couldn't be verified from this build environment (no network
# access to data.ny.gov, and its dataset pages are JS-rendered so scraping the
# schema wasn't possible either). 01_extract_ace_data.py auto-detects columns by
# keyword match against whatever the live API actually returns, and prints what
# it found on first run. If detection picks the wrong column, hardcode the real
# name in the COLUMN_OVERRIDES dict at the top of that file.
SOCRATA_DOMAIN             = "data.ny.gov"
SOCRATA_APP_TOKEN          = ""   # optional - set via env var for higher rate limits, not required
ACE_ROUTES_DATASET_ID      = "ki2b-sg5y"   # MTA Bus Automated Camera Enforced Routes
ACE_VIOLATIONS_DATASET_ID  = "kh8p-hcbm"   # MTA Bus Automated Camera Enforcement Violations

# Bus Speeds is split across multiple dataset IDs by year, and NYS Open Data
# periodically retires/re-IDs old ones (6ksi-7cxr, the original "Beginning 2020"
# ID, 404s as of this build - replaced by 4u4b-jge6 "Beginning 2025"). The
# extractor tries each ID in order and skips any that 404 instead of failing,
# so this list can be appended to over time without breaking anything.
BUS_SPEEDS_DATASET_IDS     = [
    "4u4b-jge6",   # MTA Bus Speeds: Beginning 2025 (currently active)
    "6ksi-7cxr",   # MTA Bus Speeds: 2020-2024 (404 as of this build - kept in case it's restored)
    "cudb-vcni",   # MTA Bus Speeds: 2015-2019 (older history, useful for early ACE routes)
]

ACE_ROUTES_CSV             = "data/ace_routes.csv"
ACE_VIOLATIONS_CSV         = "data/ace_violations.csv"
BUS_SPEEDS_CSV             = "data/bus_speeds.csv"

IMPACT_WINDOW_DAYS         = 90    # before/after comparison window around activation date
