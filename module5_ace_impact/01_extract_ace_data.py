"""
ACE Impact Data Extractor
Pulls three real public datasets from data.ny.gov (NYS Open Data / Socrata):

  1. MTA Bus Automated Camera Enforced Routes  (ki2b-sg5y)
     -> which routes have ACE, and since when (the "activation date" / treatment point)
  2. MTA Bus Automated Camera Enforcement Violations (kh8p-hcbm)
     -> every recorded violation, dated and route-tagged
  3. MTA Bus Speeds: Beginning 2020 (6ksi-7cxr)
     -> route-level monthly average speed - the outcome metric for before/after testing

WHY COLUMN AUTO-DETECTION:
This was built without live network access to data.ny.gov, and the dataset
pages are JS-rendered (the schema isn't visible in static HTML either), so the
exact column names in the live API response could not be verified ahead of
time. Rather than hardcode guessed names with false confidence, this script:
  - fetches a small sample from each dataset first
  - prints every column name it actually finds
  - auto-picks the most likely column for each field using keyword matching
  - lets you hardcode the verified name in COLUMN_OVERRIDES below if detection
    ever picks the wrong one (check the printed "Detected columns" lines after
    your first real run and adjust if anything looks off)

Run with: python module5_ace_impact/01_extract_ace_data.py
"""

import os, sys, csv, json, time
import urllib.request, urllib.parse, urllib.error

# CRITICAL: when stdout isn't a terminal (e.g. GitHub Actions captures it as a
# pipe), Python fully buffers print() output instead of flushing per line - so
# nothing appears in the live log until the buffer fills or the script exits.
# For a long-running scraper that's the difference between "looks hung" and
# "visibly working." Force line buffering so progress shows up immediately.
try:
    sys.stdout.reconfigure(line_buffering=True)
except AttributeError:
    pass  # older Python without reconfigure(); PYTHONUNBUFFERED env var covers it instead

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    SOCRATA_DOMAIN, SOCRATA_APP_TOKEN as CONFIG_SOCRATA_APP_TOKEN,
    ACE_ROUTES_DATASET_ID, ACE_VIOLATIONS_DATASET_ID, BUS_SPEEDS_DATASET_ID,
    ACE_ROUTES_CSV, ACE_VIOLATIONS_CSV, BUS_SPEEDS_CSV, DATA_DIR,
)

# Matches the GROQ_API_KEY / SERPAPI_KEY pattern used elsewhere in this repo:
# real secrets come from the environment (.env locally, GitHub Secrets in CI),
# not hardcoded in config.py. The token is optional - Socrata works without
# one at lower rate limits.
SOCRATA_APP_TOKEN = os.environ.get("SOCRATA_APP_TOKEN", CONFIG_SOCRATA_APP_TOKEN)

# ── Manual overrides ────────────────────────────────────────────────────────
# If auto-detection picks the wrong column for a dataset, hardcode the real
# name here (verified from the printed "Detected columns" output) and it will
# be used instead of the keyword-matched guess. Leave as None to keep auto-detect.
COLUMN_OVERRIDES = {
    "routes":     {"route": None, "date": None, "borough": None},
    "violations": {"route": None, "date": None, "status": None, "type": None},
    "speeds":     {"route": None, "period": None, "speed": None},
}

PAGE_SIZE = 5000
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MTA-ACE-Impact-Tool/1.0)"}


def socrata_url(dataset_id, limit, offset, order=None):
    params = {"$limit": limit, "$offset": offset}
    if order:
        params["$order"] = order
    return f"https://{SOCRATA_DOMAIN}/resource/{dataset_id}.json?{urllib.parse.urlencode(params)}"


def fetch_page(dataset_id, limit, offset, order=None):
    url = socrata_url(dataset_id, limit, offset, order)
    req = urllib.request.Request(url, headers=HEADERS)
    if SOCRATA_APP_TOKEN:
        req.add_header("X-App-Token", SOCRATA_APP_TOKEN)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_all(dataset_id, label, max_pages=200, order=None):
    """Paginate through a Socrata dataset until a short page signals the end."""
    all_rows = []
    offset = 0
    for page in range(max_pages):
        page_start = time.time()
        try:
            rows = fetch_page(dataset_id, PAGE_SIZE, offset, order=order)
        except urllib.error.HTTPError as e:
            print(f"   HTTP error on {label} at offset {offset}: {e.code} {e.reason}")
            break
        except Exception as e:
            print(f"   Error fetching {label} at offset {offset}: {e}")
            break

        elapsed = time.time() - page_start
        if not rows:
            break
        all_rows.extend(rows)
        print(f"   {label}: fetched {len(all_rows):,} rows so far... (page {page+1} took {elapsed:.1f}s)")
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.2)

    if len(all_rows) >= PAGE_SIZE * max_pages:
        print(f"   ⚠️  Hit max_pages cap ({max_pages}) for {label} - there may be more data than this.")

    return all_rows


def find_column(columns, keywords, exclude=()):
    """
    Case-insensitive substring match against actual column names.
    keywords: list of candidate substrings, tried in priority order.
    exclude: substrings that disqualify a column even if it matches a keyword
             (e.g. avoid matching 'violation_status_date' when looking for 'status').
    Returns the first real column name that matches, or None.
    """
    lower_to_real = {c.lower(): c for c in columns}
    for kw in keywords:
        for col_lower, col_real in lower_to_real.items():
            if kw in col_lower and not any(ex in col_lower for ex in exclude):
                return col_real
    return None


def detect_columns(rows, dataset_label, field_spec, overrides):
    """
    field_spec: dict of {field_name: (keywords_list, exclude_list)}
    overrides: dict of {field_name: forced_column_name_or_None}
    Returns dict of {field_name: detected_column_name}, printing what it found.
    """
    if not rows:
        print(f"   ⚠️  No rows returned for {dataset_label} - cannot detect columns.")
        return {f: None for f in field_spec}

    columns = list(rows[0].keys())
    print(f"\n   📋 {dataset_label} - actual columns returned by API:")
    print(f"      {columns}")

    detected = {}
    for field, (keywords, exclude) in field_spec.items():
        forced = overrides.get(field)
        if forced:
            detected[field] = forced
            print(f"      [{field}] using manual override: '{forced}'")
        else:
            found = find_column(columns, keywords, exclude)
            detected[field] = found
            status = f"'{found}'" if found else "NOT FOUND - check COLUMN_OVERRIDES"
            print(f"      [{field}] auto-detected: {status}")

    return detected


def save_csv(rows, columns_used, path):
    os.makedirs(DATA_DIR, exist_ok=True)
    if not rows:
        # still write a header-only file so downstream code degrades gracefully
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(list(columns_used.values()))
        print(f"   💾 No data - wrote empty file with headers → {path}")
        return

    fieldnames = sorted({k for row in rows for k in row.keys()})
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"   💾 Saved {len(rows):,} rows → {path}")


# ══════════════════════════════════════════════════════════════════════════════
# DATASET 1 - ACE Enforced Routes (which routes, since when)
# ══════════════════════════════════════════════════════════════════════════════

def extract_ace_routes():
    print("\n🚌 Fetching ACE Enforced Routes...")
    rows = fetch_all(ACE_ROUTES_DATASET_ID, "ACE routes")
    field_spec = {
        "route":   (["route_id", "bus_route", "route"], []),
        "date":    (["activation", "implementation", "effective_date", "start_date", "ace_date", "date"], []),
        "borough": (["borough"], []),
    }
    cols = detect_columns(rows, "ACE Enforced Routes", field_spec, COLUMN_OVERRIDES["routes"])
    save_csv(rows, cols, ACE_ROUTES_CSV)
    return rows, cols


# ══════════════════════════════════════════════════════════════════════════════
# DATASET 2 - ACE Violations (every violation, dated and route-tagged)
# ══════════════════════════════════════════════════════════════════════════════

def extract_ace_violations():
    print("\n📸 Fetching ACE Violations...")
    print("   Note: this dataset has been growing since 2019 and may have 500k+ rows.")
    print("   Capping at 150,000 rows (30 pages) for a reasonable run time - the impact")
    print("   engine only needs violations near each route's activation date, not the")
    print("   full history. Raise max_pages below once you've confirmed this works.")
    rows = fetch_all(ACE_VIOLATIONS_DATASET_ID, "ACE violations", max_pages=30)
    field_spec = {
        "route":  (["bus_route_id", "route_id", "route"], []),
        "date":   (["first_occurrence", "violation_date", "issue_date", "date"], []),
        "status": (["violation_status", "status"], []),
        "type":   (["violation_type", "type"], []),
    }
    cols = detect_columns(rows, "ACE Violations", field_spec, COLUMN_OVERRIDES["violations"])
    save_csv(rows, cols, ACE_VIOLATIONS_CSV)
    return rows, cols


# ══════════════════════════════════════════════════════════════════════════════
# DATASET 3 - Bus Speeds (the outcome metric: route-level monthly avg speed)
# ══════════════════════════════════════════════════════════════════════════════

def extract_bus_speeds():
    print("\n🚍 Fetching MTA Bus Speeds (Beginning 2020)...")
    rows = fetch_all(BUS_SPEEDS_DATASET_ID, "bus speeds")
    field_spec = {
        "route":  (["route_id", "bus_route", "route"], []),
        "period": (["month", "period", "date"], []),
        "speed":  (["average_speed", "speed_mph", "speed"], []),
    }
    cols = detect_columns(rows, "Bus Speeds", field_spec, COLUMN_OVERRIDES["speeds"])
    save_csv(rows, cols, BUS_SPEEDS_CSV)
    return rows, cols


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  ACE Impact Data Extractor")
    print("  Pulling real public datasets from data.ny.gov")
    print("=" * 60)

    routes_rows, routes_cols = extract_ace_routes()
    viol_rows, viol_cols     = extract_ace_violations()
    speed_rows, speed_cols   = extract_bus_speeds()

    print("\n" + "=" * 60)
    print("  ✅ Done")
    print(f"     ACE routes:     {len(routes_rows):,} rows  → {ACE_ROUTES_CSV}")
    print(f"     ACE violations: {len(viol_rows):,} rows  → {ACE_VIOLATIONS_CSV}")
    print(f"     Bus speeds:     {len(speed_rows):,} rows  → {BUS_SPEEDS_CSV}")
    print("=" * 60)

    any_missing = any(v is None for cols in (routes_cols, viol_cols, speed_cols) for v in cols.values())
    if any_missing:
        print("\n⚠️  Some columns could not be auto-detected (see 'NOT FOUND' above).")
        print("   Open this file and set the real column name in COLUMN_OVERRIDES,")
        print("   then re-run. The 'actual columns returned by API' list printed")
        print("   above each dataset shows everything available to choose from.")
        sys.exit(1)


if __name__ == "__main__":
    main()
