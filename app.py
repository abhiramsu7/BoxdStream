from flask import Flask, render_template, request, redirect, url_for, flash
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import concurrent.futures
import csv
import io
from datetime import datetime
from difflib import SequenceMatcher
import urllib.parse 

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_flash_messages'

TMDB_API_KEY = "5b421e05cad15891667ec28db3d9b9ac"
MAX_WORKERS = 15 

# Session with Retry
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

# === 1. ALIASES ===
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
    "jigris": "Jigra",
    "jigra": "Jigra",
    "spirit": "Spirit Prabhas",
    "salaar 2": "Salaar: Part 2 – Shouryanga Parvam",
    "shouryanga parvam": "Salaar: Part 2 – Shouryanga Parvam",
    "kalki 2": "Kalki 2",
    "animal park": "Animal Park",
    "kantara 2": "Kantara: Chapter 1",
    "jai hanuman": "Jai Hanuman",
    "fauzi": "Fauji"
}

# === 2. CUSTOM METADATA ===
CUSTOM_METADATA = {
    "John Wick: Chapter 5": {
        "poster": "https://image.tmdb.org/t/p/original/tM9vBvLg4g4Vv7w4x9w4x9w4.jpg"
    }
}

# === 3. HELPER FUNCTIONS ===
def get_direct_link(provider_name, movie_title):
    q = urllib.parse.quote(movie_title)
    p = provider_name.lower()
    if any(x in p for x in ["jio", "hotstar", "disney", "jiostar"]): return f"https://www.hotstar.com/in/search?q={q}"
    if "netflix" in p: return f"https://www.netflix.com/search?q={q}"
    if "prime" in p or "amazon" in p: return f"https://www.primevideo.com/search/ref=atv_nb_sr?phrase={q}"
    if "apple" in p: return f"https://tv.apple.com/search?term={q}"
    if "zee5" in p: return f"https://www.zee5.com/search?q={q}"
    if "sonyliv" in p: return f"https://www.sonyliv.com/search?q={q}"
    if "aha" in p: return f"https://www.aha.video/search?q={q}"
    if "sun nxt" in p: return f"https://www.sunnxt.com/search?q={q}"
    return f"https://www.google.com/search?q={q}+{urllib.parse.quote(provider_name)}"

def get_providers(tmdb_id, media_type, region):
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/watch/providers?api_key={TMDB_API_KEY}"
    try:
        response = session.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if "results" in data and region in data["results"]:
                return data["results"][region]
    except: pass
    return None

def get_collection_parts(collection_id):
    url = f"https://api.themoviedb.org/3/collection/{collection_id}?api_key={TMDB_API_KEY}"
    try:
        resp = session.get(url).json()
        parts = resp.get('parts', [])
        parts.sort(key=lambda x: x.get('release_date', '9999-99-99') or '9999-99-99')
        return parts
    except: return []

# === 4. THE GOOGLE-STYLE SORTING ALGORITHM ===
def smart_sort(results, user_query):
    """
    Sorts results so the 'Real' movie comes first.
    Prioritizes: Exact Match > Indian Content > High Vote Count > Popularity
    """
    scored_results = []
    user_query = user_query.lower().strip()

    for item in results:
        # 1. Base Score (Vote Count)
        # Classics like Indra (2002) have way more votes than junk data
        vote_score = item.get('vote_count', 0)
        
        # 2. Indian Content Boost (The "Yogi" Fix)
        # If language is Telugu/Hindi/Tamil, give it a HUGE boost
        lang = item.get('original_language', 'en')
        lang_boost = 0
        if lang in ['te', 'hi', 'ta', 'ml', 'kn']: 
            lang_boost = 5000 # Massive boost for Indian films
        
        # 3. Exact Title Match Boost
        title = item.get('title') or item.get('name') or ""
        match_boost = 0
        if title.lower().strip() == user_query:
            match_boost = 2000
            
        # 4. Popularity (Tie breaker)
        pop_score = item.get('popularity', 0)

        # Final Score Calculation
        final_score = vote_score + lang_boost + match_boost + pop_score
        
        item['smart_score'] = final_score
        scored_results.append(item)

    # Sort High to Low
    scored_results.sort(key=lambda x: x['smart_score'], reverse=True)
    return scored_results

# === 5. MAIN PROCESSING ===
def process_single_search(query, region, tmdb_id=None, media_type="movie", year=None):
    clean_query = query.strip().lower()
    if clean_query in SEARCH_ALIASES:
        final_query = SEARCH_ALIASES[clean_query]
    else:
        final_query = query

    movies_to_process = []

    # --- IF SEARCHING BY NAME (Logic Upgrade) ---
    if not tmdb_id:
        url = "https://api.themoviedb.org/3/search/multi"
        params = {"api_key": TMDB_API_KEY, "query": final_query, "include_adult": "false", "page": 1}
        
        try:
            resp = session.get(url, params=params).json()
            raw_results = [r for r in resp.get('results', []) if r.get('media_type') in ['movie', 'tv']]
            
            if raw_results:
                # APPLY SMART SORT HERE
                sorted_results = smart_sort(raw_results, final_query)
                
                # Pick the top winner
                first_hit = sorted_results[0]
                
                # Franchise Check
                m_type = first_hit.get('media_type', 'movie')
                if m_type == 'movie':
                    details_url = f"https://api.themoviedb.org/3/movie/{first_hit['id']}?api_key={TMDB_API_KEY}"
                    details = session.get(details_url).json()
                    collection = details.get('belongs_to_collection')
                    if collection:
                        parts = get_collection_parts(collection['id'])
                        for p in parts: p['media_type'] = 'movie' 
                        movies_to_process = parts
                    else:
                        movies_to_process = [first_hit]
                else:
                    movies_to_process = [first_hit]
            else:
                 return [{
                    'title': query, 'year': "Unknown", 'poster': None, 'providers': [],
                    'status': "Not Found", 'ui_class': "not-found", 'justwatch_link': "#"
                }]
        except:
             return [{
                    'title': query, 'year': "Error", 'poster': None, 'providers': [],
                    'status': "Error", 'ui_class': "not-found", 'justwatch_link': "#"
                }]
    else:
        # ID provided case
        details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        try:
            first_hit = session.get(details_url).json()
            if 'media_type' not in first_hit: first_hit['media_type'] = media_type
            movies_to_process = [first_hit]
        except: pass

    # --- PROCESS FINAL LIST ---
    final_results = []
    for item in movies_to_process:
        m_id = item['id']
        m_type = item.get('media_type', 'movie')
        m_title = item.get('title') or item.get('name')
        m_date = item.get('release_date') or item.get('first_air_date') or "N/A"
        m_poster = item.get('poster_path')
        
        # Poster
        poster_url = f"https://image.tmdb.org/t/p/w500{m_poster}" if m_poster else "https://via.placeholder.com/500x750?text=No+Poster"
        if m_title in CUSTOM_METADATA and not m_poster: poster_url = CUSTOM_METADATA[m_title]['poster']

        # Providers
        providers = get_providers(m_id, m_type, region)
        processed_providers = []
        if providers:
            def add_provider(p_data, label):
                link = get_direct_link(p_data['provider_name'], m_title)
                return {'name': p_data['provider_name'], 'logo': f"https://image.tmdb.org/t/p/w92{p_data['logo_path']}", 'label': label, 'link': link}
            if 'flatrate' in providers: 
                for p in providers['flatrate']: processed_providers.append(add_provider(p, 'Subscription'))
            if 'rent' in providers: 
                for p in providers['rent']: processed_providers.append(add_provider(p, 'Rent'))
            if 'buy' in providers: 
                for p in providers['buy']: 
                    if not any(x['name'] == p['provider_name'] for x in processed_providers): processed_providers.append(add_provider(p, 'Buy'))

        # Status
        status = "Not Streaming"
        ui_class = "released-unknown"
        if processed_providers:
            status = "Streaming"
            ui_class = "streaming"
        else:
            is_future = False
            if not m_date or m_date == "N/A": is_future = True
            else:
                try: 
                    if datetime.strptime(m_date, "%Y-%m-%d") > datetime.now(): is_future = True
                except: pass
            
            if is_future:
                status = "Coming Soon"
                ui_class = "unreleased"
                if not m_date or m_date == "N/A": m_date = "TBA"
            else:
                status = "Not Streaming" 
                ui_class = "not-streaming" 

        final_results.append({
            'title': m_title,
            'year': m_date.split('-')[0] if '-' in str(m_date) else m_date,
            'poster': poster_url, 
            'providers': processed_providers,
            'status': status,
            'ui_class': ui_class,
            'justwatch_link': f"https://www.justwatch.com/{region.lower()}/search?q={m_title}"
        })

    return final_results

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        mode = request.form.get('mode')
        region = request.form.get('region_code', 'IN')
        
        if mode == 'search':
            title = request.form.get('title')
            tmdb_id = request.form.get('tmdb_id')
            media_type = request.form.get('media_type')
            results = process_single_search(title, region, tmdb_id, media_type)
            
            if not results or results[0]['status'] == "Not Found":
                flash(f"Could not find results for '{title}'.", "error")
                return redirect(url_for('index'))
            return render_template('results.html', results=results, region=region, summary={})

        elif mode == 'csv':
            if 'file' not in request.files: return redirect(url_for('index'))
            file = request.files['file']
            try:
                stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
                csv_input = csv.DictReader(stream)
                tasks = []
                for row in csv_input:
                    name = row.get('Name') or row.get('Title')
                    year = row.get('Year') 
                    if name: tasks.append({'name': name, 'year': year})
                
                results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    future_to_task = {executor.submit(process_single_search, t['name'], region, None, None, t['year']): t for t in tasks}
                    for future in concurrent.futures.as_completed(future_to_task):
                        try:
                            data_list = future.result()
                            if data_list: results.extend(data_list)
                        except: pass

                def sort_key(x):
                    if x['status'] == 'Streaming': return 0
                    if x['status'] == 'Coming Soon': return 1
                    return 2
                unique_results = {v['title']+v['year']:v for v in results}.values()
                results = list(unique_results)
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

# === 6. AUTOCOMPLETE ROUTE (Same Smart Logic) ===
@app.route('/api/autocomplete')
def autocomplete():
    query = request.args.get('q', '').strip().lower()
    if not query: return []

    final_query = query
    if query in SEARCH_ALIASES: final_query = SEARCH_ALIASES[query]

    url = "https://api.themoviedb.org/3/search/multi"
    params = {"api_key": TMDB_API_KEY, "query": final_query, "include_adult": "false", "language": "en-US", "page": 1}
    
    try:
        resp = session.get(url, params=params).json()
        raw_results = [r for r in resp.get('results', []) if r.get('media_type') in ['movie', 'tv']]
        
        # APPLY THE SAME SMART SORT
        sorted_results = smart_sort(raw_results, final_query)
        
        clean_results = []
        for item in sorted_results[:10]: # Return top 10 Sorted
            title = item.get('title') or item.get('name')
            date = item.get('release_date') or item.get('first_air_date') or ""
            year = date.split('-')[0] if date else ""
            
            clean_results.append({
                "title": title,
                "year": year,
                "tmdb_id": item['id'],
                "media_type": item['media_type'],
                "score": item['smart_score'] # For debugging
            })
        return clean_results
    except: return []

if __name__ == '__main__':
    app.run(debug=True)