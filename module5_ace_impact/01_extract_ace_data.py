"""
ACE Impact Data Extractor
Pulls real public datasets from data.ny.gov (NYS Open Data / Socrata):

  1. MTA Bus Automated Camera Enforced Routes  (ki2b-sg5y)
     -> which routes have ACE, and since when (the "activation date" / treatment point)
     -> CONFIRMED columns: route, program, implementation_date
  2. MTA Bus Automated Camera Enforcement Violations (kh8p-hcbm)
     -> every recorded violation, dated and route-tagged
     -> CONFIRMED columns: violation_id, vehicle_id, first_occurrence, last_occurrence,
        violation_status, violation_type, bus_route_id, violation_latitude/longitude,
        stop_id, stop_name, bus_stop_latitude/longitude, *_georeference
  3. MTA Bus Speeds (route-level monthly average speed - the outcome metric)
     -> split/re-published across multiple dataset IDs by year; NYS Open Data
        periodically retires old IDs (e.g. the original "Beginning 2020" ID,
        6ksi-7cxr, 404s as of this build). BUS_SPEEDS_DATASET_IDS in config.py
        is tried in order and 404s are skipped gracefully rather than failing
        the whole run - append new IDs there as datasets get re-versioned again.

WHY COLUMN AUTO-DETECTION (still used for the speeds dataset):
This was built without live network access to data.ny.gov, and the dataset
pages are JS-rendered (the schema isn't visible in static HTML either), so
exact column names had to be confirmed by an actual run instead of guessed
ahead of time. Datasets 1 and 2's columns are now confirmed and hardcoded
above in COLUMN_OVERRIDES. Dataset 3 is still on auto-detect since its
dataset IDs changed after the original build and haven't been run live yet -
check the printed "actual columns returned by API" output and hardcode into
COLUMN_OVERRIDES["speeds"] once confirmed.

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
    ACE_ROUTES_DATASET_ID, ACE_VIOLATIONS_DATASET_ID, BUS_SPEEDS_DATASET_IDS,
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
#
# routes/violations below are CONFIRMED from a real run against the live API
# (see conversation history) - hardcoded directly rather than left to guess.
# speeds is still auto-detect since BUS_SPEEDS_DATASET_IDS changed and hasn't
# been run against live data yet.
COLUMN_OVERRIDES = {
    "routes":     {"route": "route", "date": "implementation_date", "borough": None},  # no borough column exists - that's fine, it's optional
    "violations": {"route": "bus_route_id", "date": "first_occurrence", "status": "violation_status", "type": "violation_type"},
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
    """Paginate through a Socrata dataset until a short page signals the end.
    Returns (rows, dead) where dead=True means the FIRST request 404'd (the
    dataset ID itself is gone/retired), distinct from "dataset exists but is
    legitimately empty"."""
    all_rows = []
    offset = 0
    for page in range(max_pages):
        page_start = time.time()
        try:
            rows = fetch_page(dataset_id, PAGE_SIZE, offset, order=order)
        except urllib.error.HTTPError as e:
            if page == 0:
                print(f"   ✗ {label} ({dataset_id}): {e.code} {e.reason} - this dataset ID looks retired/invalid, skipping.")
                return [], True
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

    return all_rows, False


def fetch_all_multi(dataset_ids, label, max_pages_per_id=15, order=None):
    """
    Try multiple dataset IDs (e.g. the same logical dataset split/re-published
    across years) and merge whatever succeeds. IDs that 404 are logged and
    skipped rather than treated as fatal - NYS Open Data periodically retires
    and re-IDs datasets, and this should keep working when that happens again.
    """
    combined = []
    for dataset_id in dataset_ids:
        rows, dead = fetch_all(dataset_id, f"{label} ({dataset_id})", max_pages=max_pages_per_id, order=order)
        if dead:
            continue
        combined.extend(rows)
    return combined


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
    field_spec: dict of {field_name: (keywords_list, exclude_list, required_bool)}
    overrides: dict of {field_name: forced_column_name_or_None}
    Returns dict of {field_name: detected_column_name}, printing what it found.
    Fields marked required=False that aren't found are noted but don't fail the run.
    """
    if not rows:
        print(f"   ⚠️  No rows returned for {dataset_label} - cannot detect columns.")
        return {f: None for f in field_spec}

    columns = list(rows[0].keys())
    print(f"\n   📋 {dataset_label} - actual columns returned by API:")
    print(f"      {columns}")

    detected = {}
    for field, (keywords, exclude, required) in field_spec.items():
        forced = overrides.get(field)
        if forced:
            detected[field] = forced
            print(f"      [{field}] using manual override: '{forced}'")
        else:
            found = find_column(columns, keywords, exclude)
            detected[field] = found
            if found:
                status = f"'{found}'"
            elif required:
                status = "NOT FOUND - check COLUMN_OVERRIDES (required)"
            else:
                status = "not found (optional, unused downstream - fine to ignore)"
            print(f"      [{field}] auto-detected: {status}")

    return detected


def missing_required(field_spec, detected):
    """True if any REQUIRED field failed to detect. Optional fields don't count."""
    return any(
        detected.get(field) is None
        for field, (_, _, required) in field_spec.items()
        if required
    )


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
    rows, dead = fetch_all(ACE_ROUTES_DATASET_ID, "ACE routes")
    field_spec = {
        "route":   (["route_id", "bus_route", "route"], [], True),
        "date":    (["activation", "implementation", "effective_date", "start_date", "ace_date", "date"], [], True),
        "borough": (["borough"], [], False),   # not used downstream - fine if missing
    }
    cols = detect_columns(rows, "ACE Enforced Routes", field_spec, COLUMN_OVERRIDES["routes"])
    save_csv(rows, cols, ACE_ROUTES_CSV)
    return rows, cols, field_spec


# ══════════════════════════════════════════════════════════════════════════════
# DATASET 2 - ACE Violations (every violation, dated and route-tagged)
# ══════════════════════════════════════════════════════════════════════════════

def extract_ace_violations():
    print("\n📸 Fetching ACE Violations...")
    print("   Note: this dataset has been growing since 2019 and may have 500k+ rows.")
    print("   Capping at 150,000 rows (30 pages) for a reasonable run time - the impact")
    print("   engine only needs violations near each route's activation date, not the")
    print("   full history. Raise max_pages below once you've confirmed this works.")
    rows, dead = fetch_all(ACE_VIOLATIONS_DATASET_ID, "ACE violations", max_pages=30)
    field_spec = {
        "route":  (["bus_route_id", "route_id", "route"], [], True),
        "date":   (["first_occurrence", "violation_date", "issue_date", "date"], [], True),
        "status": (["violation_status", "status"], [], False),
        "type":   (["violation_type", "type"], [], False),
    }
    cols = detect_columns(rows, "ACE Violations", field_spec, COLUMN_OVERRIDES["violations"])
    save_csv(rows, cols, ACE_VIOLATIONS_CSV)
    return rows, cols, field_spec


# ══════════════════════════════════════════════════════════════════════════════
# DATASET 3 - Bus Speeds (the outcome metric: route-level monthly avg speed)
# ══════════════════════════════════════════════════════════════════════════════

def extract_bus_speeds():
    print(f"\n🚍 Fetching MTA Bus Speeds across {len(BUS_SPEEDS_DATASET_IDS)} dataset ID(s)...")
    print("   This dataset is split/re-published by year and old IDs get retired -")
    print("   trying each known ID and merging whatever's still live.")
    rows = fetch_all_multi(BUS_SPEEDS_DATASET_IDS, "bus speeds", max_pages_per_id=15)
    field_spec = {
        "route":  (["route_id", "bus_route", "route"], [], True),
        "period": (["month", "period", "date"], [], True),
        "speed":  (["average_speed", "speed_mph", "speed"], [], True),
    }
    cols = detect_columns(rows, "Bus Speeds", field_spec, COLUMN_OVERRIDES["speeds"])
    save_csv(rows, cols, BUS_SPEEDS_CSV)
    return rows, cols, field_spec


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  ACE Impact Data Extractor")
    print("  Pulling real public datasets from data.ny.gov")
    print("=" * 60)

    routes_rows, routes_cols, routes_spec = extract_ace_routes()
    viol_rows, viol_cols, viol_spec       = extract_ace_violations()
    speed_rows, speed_cols, speed_spec    = extract_bus_speeds()

    print("\n" + "=" * 60)
    print("  ✅ Done")
    print(f"     ACE routes:     {len(routes_rows):,} rows  → {ACE_ROUTES_CSV}")
    print(f"     ACE violations: {len(viol_rows):,} rows  → {ACE_VIOLATIONS_CSV}")
    print(f"     Bus speeds:     {len(speed_rows):,} rows  → {BUS_SPEEDS_CSV}")
    print("=" * 60)

    fatal = (
        missing_required(routes_spec, routes_cols)
        or missing_required(viol_spec, viol_cols)
        or missing_required(speed_spec, speed_cols)
    )
    if fatal:
        print("\n⚠️  A REQUIRED column could not be auto-detected (see 'required' lines above).")
        print("   Open this file and set the real column name in COLUMN_OVERRIDES,")
        print("   then re-run. The 'actual columns returned by API' list printed")
        print("   above each dataset shows everything available to choose from.")
        sys.exit(1)
    elif not speed_rows:
        print("\n⚠️  No bus speed data was retrieved from ANY dataset ID - check")
        print("   BUS_SPEEDS_DATASET_IDS in config.py, the retired ones may all be")
        print("   gone and a new current ID may be needed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
