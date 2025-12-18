import requests
import csv
import io
import os
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, render_template, request
from concurrent.futures import ThreadPoolExecutor

MAX_WORKERS = 10

# =========================
# MOVIE MODEL
# =========================
class Movie:
    def __init__(self, title, year, tmdb_id=None, media_type="movie"):
        self.title = title
        self.year = year
        self.tmdb_id = tmdb_id
        self.poster_path = None
        self.is_released = False
        self.release_date = None
        self.streaming_info = {}
        self.media_type = media_type

    def __str__(self):
        if not self.is_released:
            return "Not Yet Released"
        if not self.streaming_info:
            return "Released – Availability Unknown / Not Streaming in Region"
        providers = [f"{k} ({v})" for k, v in self.streaming_info.items()]
        return f"Available on: {', '.join(providers)}"

    def get_category(self):
        """Returns the single primary category for the summary counter"""
        status = str(self)
        if "Subscription" in status:
            return "available_free"
        elif "Rent" in status or "Buy" in status:
            return "rent_or_buy"
        elif "Not Yet Released" in status:
            return "unreleased"
        else:
            return "unknown"

    def to_dict(self):
        status_text = str(self)
        # UI Class logic
        if "Subscription" in status_text:
            ui_class = "available"
        elif "Rent" in status_text:
            ui_class = "rent"
        elif "Not Yet Released" in status_text:
            ui_class = "not-released"
        else:
            ui_class = "released-unknown"

        title_display = self.title
        if self.media_type == "tv":
            title_display = f"{self.title} (TV)"

        return {
            "title": title_display,
            "year": self.year,
            "status": status_text,
            "ui_class": ui_class,
            "poster": (
                f"https://image.tmdb.org/t/p/w342{self.poster_path}"
                if self.poster_path else None
            ),
            "media_type": self.media_type
        }

# =========================
# TMDB CLIENT
# =========================
class TMDBClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.today = datetime.now().date()

        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504])
        adapter = HTTPAdapter(max_retries=retry)
        self.session = requests.Session()
        self.session.mount("https://", adapter)

    def _get(self, url, params):
        try:
            r = self.session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except:
            return None

    def search_movie(self, movie):
        """
        OPTIMIZED SEARCH:
        1. If movie already has an ID (from dropdown), fetch details directly.
        2. If not, use Smart Multi-Search.
        """
        
        # === OPTIMIZATION: DIRECT ID LOOKUP ===
        if movie.tmdb_id:
            # We already know exactly what to look for. No searching needed.
            return self._fetch_details_by_id(movie)

        # === FALLBACK: TEXT SEARCH (For CSVs) ===
        params = {
            "api_key": self.api_key, 
            "query": movie.title,
            "include_adult": "false"
        }
        
        data = self._get(f"{self.base_url}/search/multi", params)
        if not data or not data.get("results"):
            return False

        valid_results = [r for r in data["results"] if r["media_type"] in ["movie", "tv"]]
        if not valid_results:
            return False

        best_match = None
        if movie.year and movie.year != "0000":
            for r in valid_results:
                r_date = r.get("release_date") or r.get("first_air_date")
                if r_date and r_date.split("-")[0] == movie.year:
                    best_match = r
                    break
        
        if not best_match:
            best_match = valid_results[0]

        movie.media_type = best_match["media_type"]
        movie.tmdb_id = best_match["id"]
        
        return self._fetch_details_by_id(movie)

    def _fetch_details_by_id(self, movie):
        """Helper to get poster and release date once we have an ID"""
        endpoint = f"{self.base_url}/{movie.media_type}/{movie.tmdb_id}"
        data = self._get(endpoint, {"api_key": self.api_key})
        
        if not data:
            return False

        movie.poster_path = data.get("poster_path")
        
        date_key = "release_date" if movie.media_type == "movie" else "first_air_date"
        release_date = data.get(date_key)

        if release_date:
            movie.release_date = release_date
            movie.year = release_date.split("-")[0]
            try:
                movie.is_released = datetime.strptime(release_date, "%Y-%m-%d").date() <= self.today
            except:
                movie.is_released = True
        elif movie.poster_path:
            movie.is_released = True
            
        return True

    def get_providers(self, movie, region):
        if not movie.tmdb_id or not movie.is_released:
            return

        endpoint = f"{self.base_url}/{movie.media_type}/{movie.tmdb_id}/watch/providers"
        
        data = self._get(endpoint, {"api_key": self.api_key})
        if not data or region not in data.get("results", {}):
            return

        r = data["results"][region]
        for key, label in [("flatrate","Subscription (Free)"),
                           ("buy","Rent/Buy (Extra Cost)"),
                           ("rent","Rent (Extra Cost)")]:
            for p in r.get(key, []):
                
                provider_name = p["provider_name"]
                p_lower = provider_name.lower()

                if region == "IN":
                    if "hotstar" in p_lower or "jio" in p_lower or "disney" in p_lower:
                        provider_name = "JioHotstar"
                else:
                    if "hotstar" in p_lower:
                        provider_name = "Disney+"

                movie.streaming_info.setdefault(provider_name, label)

# =========================
# WATCHLIST
# =========================
class Watchlist:
    def __init__(self):
        self.movies = []

    def load_csv(self, file):
        reader = csv.DictReader(file.read().decode("utf-8").splitlines())
        for row in reader:
            if row.get("Name") and row.get("Year"):
                self.movies.append(Movie(row["Name"], row["Year"]))

    def process(self, client, region):
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            for m in self.movies:
                ex.submit(self._process_one, m, client, region)
        return self.movies  # Return objects, not dicts, so we can count categories

    def _process_one(self, movie, client, region):
        if client.search_movie(movie):
            client.get_providers(movie, region)

# =========================
# FLASK APP
# =========================
app = Flask(__name__)

API_KEY = os.environ.get("API_KEY", "5b421e05cad15891667ec28db3d9b9ac")
DEFAULT_REGION = "IN"

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        mode = request.form.get("mode", "csv")
        region = request.form.get("region_code", DEFAULT_REGION)
        client = TMDBClient(API_KEY)
        
        results_objects = []

        if mode == "search":
            title = request.form.get("title", "").strip()
            # We assume these are populated by the JS Autocomplete
            tmdb_id = request.form.get("tmdb_id")
            media_type = request.form.get("media_type", "movie")
            
            if not title:
                return render_template("index.html")
            
            # Pass ID directly if we have it
            movie = Movie(title, "0000", tmdb_id=tmdb_id, media_type=media_type)
            wl = Watchlist()
            wl.movies = [movie]
            results_objects = wl.process(client, region)
        
        else:
            file = request.files.get("file")
            if not file:
                return render_template("index.html")
            
            wl = Watchlist()
            wl.load_csv(io.BytesIO(file.read()))
            results_objects = wl.process(client, region)

        # === FIXED SUMMARY COUNTER (Priority Based) ===
        categories = [m.get_category() for m in results_objects]
        summary = {
            "available_free": categories.count("available_free"),
            "rent_or_buy": categories.count("rent_or_buy"),
            "unreleased": categories.count("unreleased"),
            "unknown": categories.count("unknown"),
            "tv_series": sum(1 for m in results_objects if m.media_type == "tv")
        }
        
        # Convert to dicts for rendering
        results_dicts = [m.to_dict() for m in results_objects]

        return render_template("results.html",
                               results=results_dicts,
                               summary=summary,
                               mode=mode)

    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')