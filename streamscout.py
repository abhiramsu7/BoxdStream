import requests
import time
import csv
import os
import io 
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename
from concurrent.futures import ThreadPoolExecutor # NEW: For concurrent processing

# Set the maximum number of simultaneous API threads (adjust based on system/network)
MAX_WORKERS = 10 

# ====================================================================
# PHASE 1: THE BLUEPRINT (OOP - Object-Oriented Programming)
# ====================================================================

class Movie:
    """Represents a single movie and its streaming availability."""
    def __init__(self, title, year):
        self.title = title
        self.year = year
        self.tmdb_id = None
        self.is_released = False
        self.release_date = None
        self.streaming_info = {} 

    def __str__(self):
        """Returns a formatted string of the movie's status."""
        
        status = "N/A"
        
        if not self.is_released:
            if self.release_date:
                try:
                    formatted_date = datetime.strptime(self.release_date, '%Y-%m-%d').strftime('%B %d, %Y')
                    status = f"Not Yet Released (Expected: {formatted_date})"
                except ValueError:
                    status = "Not Yet Released (Date Format Error)"
            else:
                status = "Not Yet Released (Date Unknown)"
        else:
            if not self.streaming_info:
                status = "Released - Availability Unknown/Not Streaming in Region"
            else:
                providers = [f"{name} ({type_})" for name, type_ in self.streaming_info.items()]
                status = f"Available on: {', '.join(providers)}"
        
        return f"{self.title} ({self.year}) | Status: {status}"

    def to_dict(self):
        """Converts the Movie object to a dictionary for easy display in Flask/Jinja2."""
        status_text = self.__str__().split('| Status: ')[-1].strip()
        
        # Determine the status class/icon for the UI
        if 'Subscription (Free)' in status_text:
            ui_class = 'available'
            icon = '✅'
        elif 'Rent/Buy' in status_text or 'Rent (Extra Cost)' in status_text:
            ui_class = 'rent'
            icon = '💰'
        elif 'Not Yet Released' in status_text:
            ui_class = 'not-released'
            icon = '📅'
        else:
            ui_class = 'released-unknown'
            icon = '❌'

        return {
            'title': self.title,
            'year': self.year,
            'status': status_text,
            'ui_class': ui_class,
            'icon': icon,
            'streaming_info': self.streaming_info
        }

# ====================================================================
# PHASE 2: THE LOGIC (API Integration & Error Handling)
# ====================================================================

class TMDBClient:
    """Handles all communication with The Movie Database API using a persistent session."""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.today = datetime.now().date()
        
        retry_strategy = Retry(
            total=3, 
            backoff_factor=1, 
            status_forcelist=[429, 500, 502, 503, 504], 
            allowed_methods=["HEAD", "GET", "OPTIONS"],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        
    def _make_request(self, url, params, timeout=30):
        """Private method to execute the request using the shared session."""
        try:
            response = self.session.get(url, params=params, timeout=timeout)
            response.raise_for_status() 
            return response.json()
        except requests.exceptions.RequestException:
            return None

    def search_movie(self, movie_obj):
        """Uses the robust session for searching."""
        url = f"{self.base_url}/search/movie"
        params = {
            "api_key": self.api_key,
            "query": movie_obj.title,
            "year": movie_obj.year
        }
        
        data = self._make_request(url, params)
        
        if data and data.get('results'):
            first_match = data['results'][0]
            movie_obj.tmdb_id = first_match['id']
            
            release_date_str = first_match.get('release_date')
            movie_obj.release_date = release_date_str
            
            if release_date_str:
                try:
                    release_date_obj = datetime.strptime(release_date_str, '%Y-%m-%d').date()
                    movie_obj.is_released = release_date_obj <= self.today
                except ValueError:
                    movie_obj.is_released = False
            else:
                 movie_obj.is_released = False 

            return True
        return False

    def get_streaming_providers(self, movie_obj, region_code):
        """Uses the robust session for streaming providers."""
        
        if not movie_obj.tmdb_id or not movie_obj.is_released:
            return False

        url = f"{self.base_url}/movie/{movie_obj.tmdb_id}/watch/providers"
        params = {"api_key": self.api_key}
        
        data = self._make_request(url, params)
        
        if data and 'results' in data and region_code in data['results']:
            region_data = data['results'][region_code]
            
            if 'flatrate' in region_data:
                for provider in region_data['flatrate']:
                    movie_obj.streaming_info[provider['provider_name']] = "Subscription (Free)"
            
            if 'buy' in region_data:
                for provider in region_data['buy']:
                    if provider['provider_name'] not in movie_obj.streaming_info:
                        movie_obj.streaming_info[provider['provider_name']] = "Rent/Buy (Extra Cost)"

            elif 'rent' in region_data:
                for provider in region_data['rent']:
                    if provider['provider_name'] not in movie_obj.streaming_info:
                         movie_obj.streaming_info[provider['provider_name']] = "Rent (Extra Cost)"
                         
            return True
        
        return False

# ====================================================================
# PHASE 3: WATCHLIST CLASS (DSA & File I/O)
# ====================================================================

class Watchlist:
    """Manages reading the CSV, holding the Movie objects, and processing them."""
    
    def __init__(self):
        self.movies = [] 

    def load_from_csv(self, file_object):
        """Reads the CSV file object (from Flask upload) and populates the movies list."""
        
        self.movies = []
        try:
            file_content = file_object.read().decode('utf-8').splitlines()
            reader = csv.DictReader(file_content)
            
            for row in reader:
                title = row.get('Name')
                year = row.get('Year')
                
                if title and year:
                    self.movies.append(Movie(title, year))
                        
            return len(self.movies)

        except Exception as e:
            print(f"ERROR: Failed to read uploaded CSV: {e}")
            return 0

    def process_movie_item(self, movie, client, region_code):
        """Single thread worker function to process one movie."""
        if client.search_movie(movie):
            client.get_streaming_providers(movie, region_code)
        return movie.to_dict()

    def process_all_movies(self, client, region_code):
        """UPDATED: Uses ThreadPoolExecutor for concurrent processing."""
        
        if not self.movies:
            return []

        print(f"\n--- Starting CONCURRENT Availability Check for {len(self.movies)} Movies ---")
        
        results_list = []
        
        # ThreadPoolExecutor manages worker threads for parallel execution
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # map applies the process_movie_item function to every movie in the list
            # and collects the results (the movie.to_dict() dictionaries) in the order of the input list.
            future_results = executor.map(
                self.process_movie_item, 
                self.movies, 
                [client] * len(self.movies), 
                [region_code] * len(self.movies)
            )
            
            # Convert the iterator results into a final list
            results_list = list(future_results)
        
        print("\n--- CONCURRENT PROCESSING COMPLETE ---")
        return results_list

# ====================================================================
# PHASE 4: FLASK WEB APPLICATION SETUP 
# ====================================================================

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) 

# -----------------
# ⚠️ ACTION REQUIRED: Update these two variables 
# -----------------
API_KEY = "5b421e05cad15891667ec28db3d9b9ac" 
DEFAULT_REGION = "IN" 
# -----------------

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url) 
        
        file = request.files['file']
        region_code = request.form.get('region_code', DEFAULT_REGION).upper()
        
        if file.filename == '':
            return redirect(request.url)
        
        if file and file.filename.endswith('.csv'):
            if API_KEY == "YOUR_ACTUAL_API_KEY_HERE":
                 return render_template('index.html', error="CRITICAL: Please set your actual TMDB API Key in the Python script.")
                 
            try:
                # Use io.BytesIO to handle the file upload in memory
                file_stream = io.BytesIO(file.read())
                
                # Setup the processing objects
                client = TMDBClient(API_KEY)
                watchlist = Watchlist()
                
                # Load and Process
                watchlist.load_from_csv(file_stream)
                
                # --- Concurrency speeds up this step! ---
                results = watchlist.process_all_movies(client, region_code)
                
                # Calculate summary statistics for the UI
                summary = {
                    'total': len(results),
                    'available_free': sum(1 for r in results if 'Subscription (Free)' in r['status']),
                    'rent_or_buy': sum(1 for r in results if 'Rent/Buy' in r['status'] or 'Rent (Extra Cost)' in r['status']),
                    'unreleased': sum(1 for r in results if 'Not Yet Released' in r['status']),
                    'unknown': sum(1 for r in results if r['ui_class'] == 'released-unknown')
                }

                return render_template('results.html', 
                                       results=results, 
                                       region=region_code,
                                       movies_count=len(results),
                                       summary=summary)

            except Exception as e:
                print(f"FATAL EXCEPTION DURING PROCESSING: {e}")
                return render_template('index.html', error=f"An unexpected error occurred during processing. Please try again.")

    return render_template('index.html')

if __name__ == '__main__':
    if API_KEY == "YOUR_ACTUAL_API_KEY_HERE":
         print("CRITICAL: Please update the API_KEY variable.")
    else:
        print("Starting Flask web server...")
        app.run(debug=True, host='0.0.0.0')