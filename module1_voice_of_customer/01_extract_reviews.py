"""
Smart Data Extractor:
  1. APP_STORE_ID set → Apple App Store (iTunes RSS)
  2. APP_STORE_ID empty → Google Reviews via SerpAPI
"""

import os, sys, csv, json, time, re
import urllib.request, urllib.parse, urllib.error
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    BRAND_NAME, KEYWORDS, APP_STORE_ID, APP_COUNTRY,
    MAX_REVIEW_PAGES, DATA_DIR, REVIEWS_CSV,
)

SERPAPI_KEY = os.environ.get("SERPAPI_KEY", "")
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
FIELDNAMES = ["review_id","stars","date","title","text","source","product","version","vote_count"]


def fetch_url(url, timeout=20):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def parse_relative_date(text):
    """Convert 'a month ago', '2 years ago' etc to YYYY-MM-DD."""
    if not text:
        return datetime.now().strftime("%Y-%m-%d")
    text = text.lower().strip()
    now  = datetime.now()
    try:
        if "just now" in text or "moment" in text:
            return now.strftime("%Y-%m-%d")
        num = re.search(r'\d+', text)
        n   = int(num.group()) if num else 1
        if "year"  in text: return (now - timedelta(days=n*365)).strftime("%Y-%m-%d")
        if "month" in text: return (now - timedelta(days=n*30)).strftime("%Y-%m-%d")
        if "week"  in text: return (now - timedelta(days=n*7)).strftime("%Y-%m-%d")
        if "day"   in text: return (now - timedelta(days=n)).strftime("%Y-%m-%d")
        if "hour"  in text or "minute" in text: return now.strftime("%Y-%m-%d")
    except Exception:
        pass
    return now.strftime("%Y-%m-%d")


# ── App Store ─────────────────────────────────────────────────────────────────
def scrape_app_store():
    print(f"\n📱 Scraping Apple App Store (ID: {APP_STORE_ID})...")
    reviews = []
    for page in range(1, MAX_REVIEW_PAGES + 1):
        url = (f"https://itunes.apple.com/{APP_COUNTRY}/rss/customerreviews"
               f"/page={page}/id={APP_STORE_ID}/sortby=mostrecent/json")
        try:
            data    = json.loads(fetch_url(url))
            entries = data.get("feed", {}).get("entry", [])
            if page == 1 and entries:
                entries = entries[1:]
            if not entries:
                break
            for e in entries:
                reviews.append({
                    "review_id":  e.get("id",{}).get("label",""),
                    "stars":      e.get("im:rating",{}).get("label",""),
                    "date":       e.get("updated",{}).get("label","")[:10],
                    "title":      e.get("title",{}).get("label",""),
                    "text":       e.get("content",{}).get("label","").replace("\n"," ").strip(),
                    "source":     "app_store",
                    "product":    BRAND_NAME,
                    "version":    e.get("im:version",{}).get("label",""),
                    "vote_count": e.get("im:voteCount",{}).get("label","0"),
                })
            print(f"   Page {page}: {len(entries)} reviews (total: {len(reviews)})")
            time.sleep(0.5)
        except Exception as ex:
            print(f"   Page {page}: {ex} - stopping.")
            break
    print(f"   ✅ App Store: {len(reviews)} reviews")
    return reviews


# ── SerpAPI Google Reviews ────────────────────────────────────────────────────
def serpapi_get(params):
    params["api_key"] = SERPAPI_KEY
    url = f"https://serpapi.com/search?{urllib.parse.urlencode(params)}"
    return json.loads(fetch_url(url))


def scrape_google_maps_reviews(keyword):
    """Get Google Maps reviews for a business matching keyword."""
    reviews = []
    try:
        data    = serpapi_get({"engine":"google_maps","q":keyword,"type":"search"})
        results = data.get("local_results", [])
        if not results:
            print(f"   No Maps results for '{keyword}'")
            return []
        place    = results[0]
        data_id  = place.get("data_id","")
        name     = place.get("title", keyword)
        rating   = place.get("rating","")
        n_reviews= place.get("reviews","")
        print(f"   Found: {name} - {rating}⭐ ({n_reviews} reviews)")
        if not data_id:
            return []

        next_token = None
        for page in range(3):
            params = {"engine":"google_maps_reviews","data_id":data_id,"sort_by":"newestFirst","hl":"en"}
            if next_token:
                params["next_page_token"] = next_token
            rdata = serpapi_get(params)
            raw   = rdata.get("reviews", [])
            if not raw:
                break
            for r in raw:
                text = r.get("snippet","").replace("\n"," ").strip()
                if not text:
                    continue
                reviews.append({
                    "review_id":  r.get("review_id", f"{data_id}_{len(reviews)}"),
                    "stars":      str(r.get("rating","")),
                    "date":       parse_relative_date(r.get("date","")),
                    "title":      "",
                    "text":       text,
                    "source":     "google_maps",
                    "product":    name,
                    "version":    "",
                    "vote_count": str(r.get("likes",0)),
                })
            print(f"   Page {page+1}: {len(raw)} reviews (total: {len(reviews)})")
            next_token = rdata.get("serpapi_pagination",{}).get("next_page_token","")
            if not next_token:
                break
            time.sleep(0.4)
    except Exception as ex:
        print(f"   Maps error for '{keyword}': {ex}")
    return reviews


def scrape_serpapi():
    if not SERPAPI_KEY:
        print("   ❌ SERPAPI_KEY not set in environment.")
        return []

    print(f"\n🔍 Scraping Google Reviews via SerpAPI for: {BRAND_NAME}...")
    all_reviews = []
    seen_ids    = set()

    for keyword in KEYWORDS[:4]:
        print(f"\n   Keyword: '{keyword}'")
        reviews = scrape_google_maps_reviews(keyword)
        for r in reviews:
            if r["review_id"] not in seen_ids:
                seen_ids.add(r["review_id"])
                all_reviews.append(r)
        time.sleep(0.5)
        if len(all_reviews) >= 300:
            break

    print(f"\n   ✅ SerpAPI: {len(all_reviews)} unique reviews")
    return all_reviews


# ── Save & Main ───────────────────────────────────────────────────────────────
def save_reviews(reviews):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(REVIEWS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(reviews)
    print(f"\n   💾 Saved {len(reviews)} reviews → {REVIEWS_CSV}")


def main():
    print("=" * 55)
    print(f"  Smart Data Extractor - {BRAND_NAME}")
    print("=" * 55)

    if APP_STORE_ID.strip():
        print("\n🔍 App Store ID found → App Store mode")
        reviews = scrape_app_store()
    else:
        print("\n🔍 No App Store ID → SerpAPI mode")
        reviews = scrape_serpapi()

    if not reviews:
        print("\n⚠️  No reviews collected.")
        print("   Check SERPAPI_KEY is in GitHub Secrets")
        sys.exit(1)

    save_reviews(reviews)

    sources = {}
    for r in reviews:
        src = r.get("source","unknown")
        sources[src] = sources.get(src,0) + 1

    print("\n" + "=" * 55)
    print(f"  ✅ Done - {len(reviews)} total reviews")
    for src, count in sources.items():
        print(f"     {src}: {count}")
    print("=" * 55)


if __name__ == "__main__":
    main()
