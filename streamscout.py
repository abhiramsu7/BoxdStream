from flask import Flask, render_template, request, redirect, url_for, flash
import requests
import concurrent.futures
import csv
import io
import time

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_flash_messages'  # Needed for error messages

# === CONFIGURATION ===
TMDB_API_KEY = "5b421e05cad15891667ec28db3d9b9ac"
MAX_WORKERS = 10  # Number of parallel threads for CSV processing

# === SMART SEARCH ALIASES ===
# Helper to map common nicknames/typos to Official TMDB Titles
SEARCH_ALIASES = {
    "og": "They Call Him OG",
    "hit 3": "HIT: The Third Case",
    "hit3": "HIT: The Third Case",
    "lucky baskar": "Lucky Baskhar",
    "lucky bhaskar": "Lucky Baskhar",
    "kalki": "Kalki 2898 AD",
    "pushpa 2": "Pushpa 2: The Rule",
    "devara": "Devara: Part 1",
    "salaar": "Salaar: Part 1 – Ceasefire",
    "ssmb29": "SSMB29",
    "game changer": "Game Changer"
}

# === CORE FUNCTIONS ===

def get_providers(tmdb_id, media_type, region):
    """
    Fetches streaming availability for a specific TMDB ID in a specific region.
    """
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/watch/providers?api_key={TMDB_API_KEY}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if "results" in data and region in data["results"]:
                return data["results"][region]
    except Exception as e:
        print(f"Error fetching providers for {tmdb_id}: {e}")
    return None

def process_single_search(query, region, tmdb_id=None, media_type="movie"):
    """
    Handles a single movie search (Used for both Search Bar & CSV rows).
    """
    # 1. SMART ALIAS CHECK
    clean_query = query.strip().lower()
    if clean_query in SEARCH_ALIASES:
        final_query = SEARCH_ALIASES[clean_query]
    else:
        final_query = query

    # 2. FIND TMDB ID (If not provided)
    poster_path = None
    release_date = "N/A"
    official_title = query

    if not tmdb_id:
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={final_query}"
        try:
            resp = requests.get(search_url).json()
            if not resp.get('results'):
                return None  # Return None so we can handle "Not Found" error
            
            # Prefer movies/tv over people
            results = [r for r in resp['results'] if r['media_type'] in ['movie', 'tv']]
            if not results:
                return None

            first_hit = results[0]
            tmdb_id = first_hit['id']
            media_type = first_hit['media_type']
            official_title = first_hit.get('title') or first_hit.get('name')
            release_date = first_hit.get('release_date') or first_hit.get('first_air_date') or "N/A"
            poster_path = first_hit.get('poster_path')
        except Exception as e:
            print(f"Search API Error: {e}")
            return None
    else:
        # If ID provided (from Autocomplete), fetch details to get poster/title
        details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        try:
            first_hit = requests.get(details_url).json()
            official_title = first_hit.get('title') or first_hit.get('name')
            release_date = first_hit.get('release_date') or first_hit.get('first_air_date') or "N/A"
            poster_path = first_hit.get('poster_path')
        except:
            pass

    # 3. GET PROVIDERS
    providers = get_providers(tmdb_id, media_type, region)
    
    # 4. FORMAT DATA FOR FRONTEND
    processed_providers = []
    
    if providers:
        # Flatrate (Streaming)
        if 'flatrate' in providers:
            for p in providers['flatrate']:
                processed_providers.append({
                    'name': p['provider_name'],
                    'logo': f"https://image.tmdb.org/t/p/w92{p['logo_path']}",
                    'label': 'Subscription'
                })
        # Rent
        if 'rent' in providers:
                for p in providers['rent']:
                    processed_providers.append({
                        'name': p['provider_name'],
                        'logo': f"https://image.tmdb.org/t/p/w92{p['logo_path']}",
                        'label': 'Rent'
                    })
        # Buy (Optional)
        if 'buy' in providers:
             for p in providers['buy']:
                 # Avoid duplicates if provider is already in Rent
                 if not any(x['name'] == p['provider_name'] for x in processed_providers):
                    processed_providers.append({
                        'name': p['provider_name'],
                        'logo': f"https://image.tmdb.org/t/p/w92{p['logo_path']}",
                        'label': 'Buy'
                    })

    # Determine status class for UI
    if not processed_providers:
        # Check if movie is unreleased
        is_future = False
        try:
            if release_date != "N/A":
                year = int(release_date.split('-')[0])
                current_year = int(time.strftime("%Y"))
                if year > current_year:
                    is_future = True
        except:
            pass
            
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
        
        # --- SCENARIO 1: SINGLE SEARCH ---
        if mode == 'search':
            title = request.form.get('title')
            tmdb_id = request.form.get('tmdb_id')
            media_type = request.form.get('media_type', 'movie')

            # Process the single movie
            result = process_single_search(title, region, tmdb_id, media_type)

            # ERROR HANDLING: If process_single_search returned None
            if not result:
                flash(f"Could not find any results for '{title}'. Please check the spelling or try the exact English title.", "error")
                return redirect(url_for('index'))

            return render_template('results.html', results=[result], region=region, summary={})

        # --- SCENARIO 2: CSV UPLOAD (Multi-threaded) ---
        elif mode == 'csv':
            if 'file' not in request.files:
                flash("No file uploaded", "error")
                return redirect(url_for('index'))
            
            file = request.files['file']
            if file.filename == '':
                flash("No file selected", "error")
                return redirect(url_for('index'))

            try:
                # Read CSV
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.DictReader(stream)
                
                # Extract Titles (Letterboxd CSVs usually have 'Name' or 'Title')
                titles = []
                for row in csv_input:
                    if 'Name' in row:
                        titles.append(row['Name'])
                    elif 'Title' in row:
                        titles.append(row['Title'])
                
                # Limit to 50 for performance (optional constraint)
                titles = titles[:50]

                # Process in Parallel
                results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    # Submit all tasks
                    future_to_title = {executor.submit(process_single_search, title, region): title for title in titles}
                    
                    for future in concurrent.futures.as_completed(future_to_title):
                        data = future.result()
                        if data: # Only append valid results
                            results.append(data)

                # Calculate Summary Stats
                free_count = sum(1 for r in results if any(p['label'] == 'Subscription' for p in r['providers']))
                rent_count = sum(1 for r in results if any(p['label'] in ['Rent', 'Buy'] for p in r['providers']))
                unreleased_count = sum(1 for r in results if r['status'] == 'Coming Soon')

                summary = {
                    'available_free': free_count,
                    'rent_or_buy': rent_count,
                    'unreleased': unreleased_count
                }

                return render_template('results.html', results=results, region=region, summary=summary)

            except Exception as e:
                flash(f"Error processing CSV: {str(e)}", "error")
                return redirect(url_for('index'))

    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True)