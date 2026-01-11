from flask import Flask, render_template, request, redirect, url_for, flash
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import concurrent.futures
import csv
import io
import time
from datetime import datetime
from difflib import SequenceMatcher
import urllib.parse 

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_flash_messages'

TMDB_API_KEY = "5b421e05cad15891667ec28db3d9b9ac"
MAX_WORKERS = 15 

# Session with Retry (Prevents "Missing Movies" in CSV)
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

# === 1. UPDATED DICTIONARY (Fixes Spirit, Salaar 2, Kalki 2) ===
SEARCH_ALIASES = {
    # Existing
    "og": "They Call Him OG",
    "hit 3": "HIT: The Third Case",
    "hit3": "HIT: The Third Case",
    "lucky baskar": "Lucky Baskhar",
    "lucky bhaskar": "Lucky Baskhar",
    "kalki": "Kalki 2898 AD",
    "pushpa 2": "Pushpa 2: The Rule",
    "pushpa2": "Pushpa 2: The Rule",
    "devara": "Devara: Part 1",
    "salaar": "Salaar: Part 1 – Ceasefire",
    "ssmb29": "SSMB29",
    "game changer": "Game Changer",
    "gamechanger": "Game Changer",
    "rrr": "RRR",
    "vnb": "Vishwambhara",
    "hunter": "Hunter: The God of Sex",
    "jigris": "Jigra",
    "jigra": "Jigra",

    # === NEW FIXES ===
    "spirit": "Spirit Prabhas", # Fixes the "Horse Movie" issue
    "salaar 2": "Salaar: Part 2 – Shouryanga Parvam",
    "shouryanga parvam": "Salaar: Part 2 – Shouryanga Parvam",
    "kalki 2": "Kalki 2", # TMDB usually lists sequels as "Title 2" or "Title Part 2"
    "animal park": "Animal Park",
    "kantara 2": "Kantara: Chapter 1",
    "jai hanuman": "Jai Hanuman"
}

# === 2. DIRECT LINK GENERATOR (JioHotstar Fix) ===
def get_direct_link(provider_name, movie_title):
    q = urllib.parse.quote(movie_title)
    p = provider_name.lower()

    if any(x in p for x in ["jio", "hotstar", "disney", "jiostar"]): 
        return f"https://www.hotstar.com/in/search?q={q}" # Direct to Hotstar

    if "netflix" in p: return f"https://www.netflix.com/search?q={q}"
    if "prime" in p or "amazon" in p: return f"https://www.primevideo.com/search/ref=atv_nb_sr?phrase={q}"
    if "apple" in p: return f"https://tv.apple.com/search?term={q}"
    if "zee5" in p: return f"https://www.zee5.com/search?q={q}"
    if "sonyliv" in p: return f"https://www.sonyliv.com/search?q={q}"
    if "aha" in p: return f"https://www.aha.video/search?q={q}"
    if "sun nxt" in p: return f"https://www.sunnxt.com/search?q={q}"
    if "youtube" in p or "google" in p: return f"https://www.youtube.com/results?search_query={q}"
    
    return f"https://www.google.com/search?q={q}+{urllib.parse.quote(provider_name)}"

# === CORE FUNCTIONS ===

def calculate_similarity(a, b):
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def find_best_match(results, user_query):
    if not results: return None
    candidates = results[:10]
    best_candidate = None
    best_score = -1

    for item in candidates:
        title = item.get('title') or item.get('name') or ""
        popularity = item.get('popularity', 0)
        
        sim_score = calculate_similarity(user_query, title)
        if title.lower().startswith(user_query.lower()[:4]):
            sim_score += 0.2

        final_score = (sim_score * 100) + (popularity * 0.02)
        
        if final_score > best_score:
            best_score = final_score
            best_candidate = item
            
    return best_candidate

def get_providers(tmdb_id, media_type, region):
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/watch/providers?api_key={TMDB_API_KEY}"
    try:
        response = session.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if "results" in data and region in data["results"]:
                return data["results"][region]
    except:
        pass
    return None

def process_single_search(query, region, tmdb_id=None, media_type="movie"):
    official_title = query
    poster_path = None
    release_date_str = "N/A"
    
    clean_query = query.strip().lower()
    if clean_query in SEARCH_ALIASES:
        final_query = SEARCH_ALIASES[clean_query]
    else:
        final_query = query

    # --- 1. FIND MOVIE ---
    if not tmdb_id:
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={final_query}&include_adult=false"
        try:
            resp = session.get(search_url).json()
            valid_results = [r for r in resp.get('results', []) if r['media_type'] in ['movie', 'tv']]
            
            if valid_results:
                first_hit = find_best_match(valid_results, final_query)
                tmdb_id = first_hit['id']
                media_type = first_hit['media_type']
                official_title = first_hit.get('title') or first_hit.get('name')
                release_date_str = first_hit.get('release_date') or first_hit.get('first_air_date') or "N/A"
                poster_path = first_hit.get('poster_path')
            else:
                # Placeholders for Not Found
                return {
                    'title': query, 'year': "Unknown", 'poster': None, 'providers': [],
                    'status': "Not Found", 'ui_class': "not-found", 'justwatch_link': "#"
                }
        except:
             return {
                    'title': query, 'year': "Error", 'poster': None, 'providers': [],
                    'status': "Error", 'ui_class': "not-found", 'justwatch_link': "#"
                }
    else:
        details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        try:
            first_hit = session.get(details_url).json()
            official_title = first_hit.get('title') or first_hit.get('name')
            release_date_str = first_hit.get('release_date') or first_hit.get('first_air_date') or "N/A"
            poster_path = first_hit.get('poster_path')
        except:
            pass

    # --- 2. GET PROVIDERS ---
    providers = get_providers(tmdb_id, media_type, region)
    processed_providers = []
    
    if providers:
        def add_provider(p_data, label):
            link = get_direct_link(p_data['provider_name'], official_title)
            return {
                'name': p_data['provider_name'],
                'logo': f"https://image.tmdb.org/t/p/w92{p_data['logo_path']}",
                'label': label,
                'link': link
            }

        if 'flatrate' in providers:
            for p in providers['flatrate']: processed_providers.append(add_provider(p, 'Subscription'))
        if 'rent' in providers:
            for p in providers['rent']: processed_providers.append(add_provider(p, 'Rent'))
        if 'buy' in providers:
            for p in providers['buy']:
                if not any(x['name'] == p['provider_name'] for x in processed_providers):
                    processed_providers.append(add_provider(p, 'Buy'))

    # --- 3. STATUS LOGIC (Fixed for Unreleased) ---
    status = "Not Streaming"
    ui_class = "released-unknown"

    if processed_providers:
        status = "Streaming"
        ui_class = "streaming"
    else:
        # Check if Future Date OR Date is Missing (N/A)
        is_future = False
        
        # Case A: Date exists and is in future
        if release_date_str and release_date_str != "N/A":
            try:
                rel_date = datetime.strptime(release_date_str, "%Y-%m-%d")
                if rel_date > datetime.now():
                    is_future = True
            except: pass
        
        # Case B: Date is Missing (N/A) -> Likely an announced/planned movie
        # This catches "Salaar 2", "Kalki 2", etc.
        elif release_date_str == "N/A" or release_date_str == "":
            is_future = True

        if is_future:
            status = "Coming Soon"
            ui_class = "unreleased"
            if release_date_str == "N/A":
                release_date_str = "TBA" # Display TBA instead of N/A

    return {
        'title': official_title,
        'year': release_date_str.split('-')[0] if '-' in str(release_date_str) else release_date_str,
        'poster': f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
        'providers': processed_providers,
        'status': status,
        'ui_class': ui_class,
        'justwatch_link': f"https://www.justwatch.com/{region.lower()}/search?q={official_title}"
    }

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        mode = request.form.get('mode')
        region = request.form.get('region_code', 'IN')
        
        if mode == 'search':
            title = request.form.get('title')
            tmdb_id = request.form.get('tmdb_id')
            media_type = request.form.get('media_type', 'movie')
            result = process_single_search(title, region, tmdb_id, media_type)
            if not result or result['status'] == "Not Found":
                flash(f"Could not find results for '{title}'.", "error")
                return redirect(url_for('index'))
            return render_template('results.html', results=[result], region=region, summary={})

        elif mode == 'csv':
            if 'file' not in request.files: return redirect(url_for('index'))
            file = request.files['file']
            
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.DictReader(stream)
                titles = []
                for row in csv_input:
                    if 'Name' in row: titles.append(row['Name'])
                    elif 'Title' in row: titles.append(row['Title'])
                
                # --- PROCESS ALL TITLES ---
                results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    future_to_title = {executor.submit(process_single_search, title, region): title for title in titles}
                    for future in concurrent.futures.as_completed(future_to_title):
                        try:
                            data = future.result()
                            if data: results.append(data)
                        except: pass

                # Sort: Streaming -> Coming Soon -> Not Streaming
                def sort_key(x):
                    if x['status'] == 'Streaming': return 0
                    if x['status'] == 'Coming Soon': return 1
                    return 2
                
                results.sort(key=sort_key)

                summary = {
                    'available_free': sum(1 for r in results if any(p['label'] == 'Subscription' for p in r['providers'])),
                    'rent_or_buy': sum(1 for r in results if any(p['label'] in ['Rent', 'Buy'] for p in r['providers'])),
                    'not_streaming': sum(1 for r in results if r['status'] == 'Not Streaming'),
                    'unreleased': sum(1 for r in results if r['status'] == 'Coming Soon' or r['status'] == 'Not Found')
                }
                return render_template('results.html', results=results, region=region, summary=summary)

            except Exception as e:
                flash(f"CSV Error: {str(e)}", "error")
                return redirect(url_for('index'))

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)