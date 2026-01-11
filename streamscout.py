from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import requests
import concurrent.futures
import csv
import io
import time
from difflib import SequenceMatcher
import urllib.parse 

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_flash_messages'

# === CONFIGURATION ===
TMDB_API_KEY = "5b421e05cad15891667ec28db3d9b9ac"
# Increase workers slightly to handle 130+ movies faster
MAX_WORKERS = 15 

# === 1. DICTIONARY ===
SEARCH_ALIASES = {
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
    "spirit": "Spirit",
    "jigris": "Jigra",
    "jigra": "Jigra"
}

# === 2. HELPER: SMART LINK GENERATOR ===
def get_provider_link(provider_name, movie_title):
    title_enc = urllib.parse.quote(movie_title)
    p_lower = provider_name.lower()

    if any(x in p_lower for x in ["jio", "hotstar", "disney", "jiostar"]):
        return f"https://www.jiocinema.com/search?q={title_enc}"

    if "netflix" in p_lower:
        return f"https://www.netflix.com/search?q={title_enc}"
    if "prime" in p_lower or "amazon" in p_lower:
        return f"https://www.primevideo.com/search/ref=atv_nb_sr?phrase={title_enc}"
    if "apple" in p_lower:
        return f"https://tv.apple.com/search?term={title_enc}"
    if "zee5" in p_lower:
        return f"https://www.zee5.com/search?q={title_enc}"
    if "sonyliv" in p_lower:
        return f"https://www.sonyliv.com/search?q={title_enc}"
    if "aha" in p_lower:
        return f"https://www.aha.video/search?q={title_enc}"
    if "sun nxt" in p_lower:
        return f"https://www.sunnxt.com/search?q={title_enc}"
    if "youtube" in p_lower or "google" in p_lower:
        return f"https://www.youtube.com/results?search_query={title_enc}"
    
    return f"https://www.google.com/search?q={title_enc}+{urllib.parse.quote(provider_name)}"

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
        
        if title.lower().startswith(user_query.lower()[:3]):
            sim_score += 0.2

        final_score = (sim_score * 100) + (popularity * 0.02)
        
        if final_score > best_score:
            best_score = final_score
            best_candidate = item
            
    return best_candidate

def get_providers(tmdb_id, media_type, region):
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/watch/providers?api_key={TMDB_API_KEY}"
    try:
        response = requests.get(url, timeout=3)
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
    release_date = "N/A"

    # Alias Check
    clean_query = query.strip().lower()
    if clean_query in SEARCH_ALIASES:
        final_query = SEARCH_ALIASES[clean_query]
    else:
        final_query = query

    # Find Movie
    if not tmdb_id:
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={final_query}&include_adult=false"
        try:
            resp = requests.get(search_url).json()
            valid_results = [r for r in resp.get('results', []) if r['media_type'] in ['movie', 'tv']]
            if not valid_results: return None

            first_hit = find_best_match(valid_results, final_query)
            
            tmdb_id = first_hit['id']
            media_type = first_hit['media_type']
            official_title = first_hit.get('title') or first_hit.get('name')
            release_date = first_hit.get('release_date') or first_hit.get('first_air_date') or "N/A"
            poster_path = first_hit.get('poster_path')
        except:
            return None
    else:
        details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        try:
            first_hit = requests.get(details_url).json()
            official_title = first_hit.get('title') or first_hit.get('name')
            release_date = first_hit.get('release_date') or first_hit.get('first_air_date') or "N/A"
            poster_path = first_hit.get('poster_path')
        except:
            pass

    # Get Providers
    providers = get_providers(tmdb_id, media_type, region)
    processed_providers = []
    
    if providers:
        def add_provider(p_data, label):
            link = get_provider_link(p_data['provider_name'], official_title)
            return {
                'name': p_data['provider_name'],
                'logo': f"https://image.tmdb.org/t/p/w92{p_data['logo_path']}",
                'label': label,
                'link': link
            }

        if 'flatrate' in providers:
            for p in providers['flatrate']:
                processed_providers.append(add_provider(p, 'Subscription'))
        if 'rent' in providers:
            for p in providers['rent']:
                processed_providers.append(add_provider(p, 'Rent'))
        if 'buy' in providers:
            for p in providers['buy']:
                if not any(x['name'] == p['provider_name'] for x in processed_providers):
                    processed_providers.append(add_provider(p, 'Buy'))

    # Status
    if not processed_providers:
        is_future = False
        try:
            if release_date != "N/A":
                year = int(release_date.split('-')[0])
                current_year = int(time.strftime("%Y"))
                if year > current_year: is_future = True
        except: pass
        status = "Coming Soon" if is_future else "Not Streaming"
        ui_class = "unreleased" if is_future else "released-unknown"
    else:
        status = "Streaming"
        ui_class = "streaming"

    return {
        'title': official_title,
        'year': release_date.split('-')[0] if '-' in str(release_date) else release_date,
        'poster': f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None,
        'providers': processed_providers,
        'status': status,
        'ui_class': ui_class,
        'justwatch_link': f"https://www.justwatch.com/{region.lower()}/search?q={official_title}"
    }

# === ROUTES ===
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

            if not result:
                flash(f"Could not find any results for '{title}'. Please try a different spelling.", "error")
                return redirect(url_for('index'))

            return render_template('results.html', results=[result], region=region, summary={})

        elif mode == 'csv':
            if 'file' not in request.files:
                flash("No file uploaded", "error")
                return redirect(url_for('index'))
            
            file = request.files['file']
            if file.filename == '':
                flash("No file selected", "error")
                return redirect(url_for('index'))

            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.DictReader(stream)
                titles = []
                for row in csv_input:
                    if 'Name' in row: titles.append(row['Name'])
                    elif 'Title' in row: titles.append(row['Title'])
                
                # --- LIMIT REMOVED ---
                # We are now processing ALL titles.
                # titles = titles[:50]  <-- DELETED THIS LINE

                results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    future_to_title = {executor.submit(process_single_search, title, region): title for title in titles}
                    for future in concurrent.futures.as_completed(future_to_title):
                        data = future.result()
                        if data: results.append(data)

                # IMPROVED SUMMARY STATS
                # Now we count "Not Streaming" too, so the numbers add up!
                summary = {
                    'available_free': sum(1 for r in results if any(p['label'] == 'Subscription' for p in r['providers'])),
                    'rent_or_buy': sum(1 for r in results if any(p['label'] in ['Rent', 'Buy'] for p in r['providers'])),
                    'unreleased': sum(1 for r in results if r['status'] == 'Coming Soon'),
                    'not_streaming': sum(1 for r in results if r['status'] == 'Not Streaming') # New Stat
                }

                return render_template('results.html', results=results, region=region, summary=summary)

            except Exception as e:
                flash(f"Error processing CSV: {str(e)}", "error")
                return redirect(url_for('index'))

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)