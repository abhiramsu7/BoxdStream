import requests
import csv
import io
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
    def __init__(self, title, year):
        self.title = title
        self.year = year
        self.tmdb_id = None
        self.poster_path = None
        self.is_released = False
        self.release_date = None
        self.streaming_info = {}
        self.media_type = "movie"

    def __str__(self):
        if not self.is_released:
            return "Not Yet Released"
        if not self.streaming_info:
            return "Released – Availability Unknown / Not Streaming in Region"
        providers = [f"{k} ({v})" for k, v in self.streaming_info.items()]
        return f"Available on: {', '.join(providers)}"

    def to_dict(self):
        status_text = str(self)
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
            title_display = f"{self.title} [TV Series]"

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
        if self._search_movie_endpoint(movie):
            return True
        if self._search_tv_endpoint(movie):
            return True
        return False

    def _search_movie_endpoint(self, movie):
        params = {"api_key": self.api_key, "query": movie.title}
        if movie.year and movie.year != "0000":
            params["year"] = movie.year
            
        data = self._get(f"{self.base_url}/search/movie", params)
        if not data or not data.get("results"):
            return False

        m = data["results"][0]
        movie.tmdb_id = m["id"]
        movie.poster_path = m.get("poster_path")
        movie.media_type = "movie"
        
        if movie.year == "0000" and m.get("release_date"):
            movie.year = m["release_date"].split("-")[0]

        if m.get("release_date"):
            movie.release_date = m["release_date"]
            try:
                movie.is_released = datetime.strptime(m["release_date"], "%Y-%m-%d").date() <= self.today
            except:
                movie.is_released = True
        elif movie.poster_path:
            movie.is_released = True
        
        return True

    def _search_tv_endpoint(self, movie):
        params = {"api_key": self.api_key, "query": movie.title}
        if movie.year and movie.year != "0000":
            params["first_air_date_year"] = movie.year
            
        data = self._get(f"{self.base_url}/search/tv", params)
        if not data or not data.get("results"):
            return False

        m = data["results"][0]
        movie.tmdb_id = m["id"]
        movie.poster_path = m.get("poster_path")
        movie.media_type = "tv"
        
        if movie.year == "0000" and m.get("first_air_date"):
            movie.year = m["first_air_date"].split("-")[0]

        if m.get("first_air_date"):
            movie.release_date = m["first_air_date"]
            try:
                movie.is_released = datetime.strptime(m["first_air_date"], "%Y-%m-%d").date() <= self.today
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
                movie.streaming_info.setdefault(p["provider_name"], label)

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
        return [m.to_dict() for m in self.movies]

    def _process_one(self, movie, client, region):
        if client.search_movie(movie):
            client.get_providers(movie, region)

# =========================
# FLASK APP
# =========================
app = Flask(__name__)

API_KEY = "5b421e05cad15891667ec28db3d9b9ac"
DEFAULT_REGION = "IN"

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        mode = request.form.get("mode", "csv")
        region = request.form.get("region_code", DEFAULT_REGION)
        client = TMDBClient(API_KEY)

        # Handle individual search
        if mode == "search":
            title = request.form.get("title", "").strip()
            year = request.form.get("year", "").strip()
            
            if not title:
                return render_template("index.html")
            
            if not year:
                year = ""
            
            movie = Movie(title, year if year else "0000")
            wl = Watchlist()
            wl.movies = [movie]
            results = wl.process(client, region)
        
        # Handle CSV upload
        else:
            file = request.files.get("file")
            if not file:
                return render_template("index.html")
            
            wl = Watchlist()
            wl.load_csv(io.BytesIO(file.read()))
            results = wl.process(client, region)

        summary = {
            "available_free": sum("Subscription" in r["status"] for r in results),
            "rent_or_buy": sum("Rent" in r["status"] for r in results),
            "unreleased": sum("Not Yet Released" in r["status"] for r in results),
            "unknown": sum(r["ui_class"]=="released-unknown" for r in results),
            "tv_series": sum(r["media_type"]=="tv" for r in results)
        }

        return render_template("results.html",
                               results=results,
                               summary=summary,
                               mode=mode)

    return render_template("index.html")

if __name__ == "__main__":
    # Host 0.0.0.0 makes it accessible to your mobile on the same WiFi
    app.run(debug=True, host='0.0.0.0')