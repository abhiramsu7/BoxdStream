from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import requests
import concurrent.futures
import csv
import io
import time
from difflib import SequenceMatcher
import re
from functools import lru_cache

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_flash_messages'

# === CONFIGURATION ===
TMDB_API_KEY = "5b421e05cad15891667ec28db3d9b9ac"
MAX_WORKERS = 10

# === ENHANCED SEARCH OPTIMIZATION ===

# 1. Direct Aliases (exact matches)
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
    "rrr": "RRR"
}

# 2. Expanded Popular Titles Database with metadata for instant autocomplete
POPULAR_TITLES_DB = [
    {"title": "They Call Him OG", "year": "2025", "type": "movie", "tmdb_id": 1064213, "aliases": ["og"]},
    {"title": "HIT: The Third Case", "year": "2025", "type": "movie", "tmdb_id": 1182373, "aliases": ["hit 3", "hit3"]},
    {"title": "Lucky Baskhar", "year": "2024", "type": "movie", "tmdb_id": 1034062, "aliases": ["lucky baskar"]},
    {"title": "Kalki 2898 AD", "year": "2024", "type": "movie", "tmdb_id": 951491, "aliases": ["kalki"]},
    {"title": "Pushpa 2: The Rule", "year": "2024", "type": "movie", "tmdb_id": 1043905, "aliases": ["pushpa 2", "pushpa2"]},
    {"title": "Pushpa: The Rise", "year": "2021", "type": "movie", "tmdb_id": 675327, "aliases": ["pushpa 1", "pushpa"]},
    {"title": "Devara: Part 1", "year": "2024", "type": "movie", "tmdb_id": 1034541, "aliases": ["devara"]},
    {"title": "Salaar: Part 1 – Ceasefire", "year": "2023", "type": "movie", "tmdb_id": 985939, "aliases": ["salaar", "salar"]},
    {"title": "Game Changer", "year": "2025", "type": "movie", "tmdb_id": 957222, "aliases": ["gamechanger"]},
    {"title": "RRR", "year": "2022", "type": "movie", "tmdb_id": 882569, "aliases": ["rrr"]},
    {"title": "Baahubali: The Beginning", "year": "2015", "type": "movie", "tmdb_id": 317011, "aliases": ["bahubali 1"]},
    {"title": "Baahubali 2: The Conclusion", "year": "2017", "type": "movie", "tmdb_id": 420809, "aliases": ["bahubali 2"]},
    {"title": "KGF Chapter 1", "year": "2018", "type": "movie", "tmdb_id": 496797, "aliases": ["kgf 1"]},
    {"title": "KGF Chapter 2", "year": "2022", "type": "movie", "tmdb_id": 762504, "aliases": ["kgf 2"]},
    {"title": "Tillu Square", "year": "2024", "type": "movie", "tmdb_id": 1083862, "aliases": []},
    {"title": "Hanu Man", "year": "2024", "type": "movie", "tmdb_id": 1023313, "aliases": ["hanuman"]},
    {"title": "Hi Nanna", "year": "2023", "type": "movie", "tmdb_id": 1139644, "aliases": []},
    {"title": "Eagle", "year": "2024", "type": "movie", "tmdb_id": 1092076, "aliases": []},
    {"title": "The Greatest of All Time", "year": "2024", "type": "movie", "tmdb_id": 1066262, "aliases": ["goat"]},
    {"title": "Indian 2", "year": "2024", "type": "movie", "tmdb_id": 447277, "aliases": []},
    {"title": "Maharaja", "year": "2024", "type": "movie", "tmdb_id": 1039690, "aliases": []},
    {"title": "Manjummel Boys", "year": "2024", "type": "movie", "tmdb_id": 1068540, "aliases": []},
    {"title": "Aavesham", "year": "2024", "type": "movie", "tmdb_id": 1226578, "aliases": []},
]

def normalize_query(query):
    """Normalize search query for better matching"""
    query = query.lower().strip()
    query = re.sub(r'[:\-–—]', ' ', query)
    query = re.sub(r'\s+', ' ', query)
    
    replacements = {
        'pt': 'part', 'chap': 'chapter', 'ch': 'chapter',
        '&': 'and', '2': 'two', '3': 'three',
    }
    
    words = query.split()
    normalized_words = [replacements.get(w, w) for w in words]
    return ' '.join(normalized_words)

def fuzzy_match_score(query, title):
    """Calculate similarity score between query and title"""
    query_norm = normalize_query(query)
    title_norm = normalize_query(title)
    
    # Exact match gets highest score
    if query_norm == title_norm:
        return 1.0
    
    if query_norm in title_norm:
        return 0.95
    
    query_words = set(query_norm.split())
    title_words = set(title_norm.split())
    
    if query_words.issubset(title_words):
        return 0.90
    
    return SequenceMatcher(None, query_norm, title_norm).ratio()

def instant_autocomplete_search(query, limit=8):
    """
    INSTANT autocomplete - searches local database first, then TMDB
    Returns results in milliseconds
    """
    if len(query) < 2:
        return []
    
    results = []
    seen_ids = set()  # Track seen TMDB IDs to avoid duplicates
    query_lower = query.lower().strip()
    
    # PHASE 1: INSTANT - Search local popular database (< 1ms)
    for movie in POPULAR_TITLES_DB:
        score = 0
        
        # Check exact alias match
        if query_lower in movie['aliases']:
            score = 1.0
        # Check exact title match
        elif query_lower == movie['title'].lower():
            score = 1.0
        # Check title contains query
        elif query_lower in movie['title'].lower():
            score = 0.9
        # Fuzzy match
        else:
            score = fuzzy_match_score(query, movie['title'])
        
        if score > 0.5:
            results.append({
                'title': movie['title'],
                'year': movie['year'],
                'tmdb_id': movie['tmdb_id'],
                'media_type': movie['type'],
                'score': score,
                'source': 'local'
            })
            seen_ids.add(movie['tmdb_id'])
    
    # Sort by score
    results.sort(key=lambda x: x['score'], reverse=True)
    
    # If we have excellent local results, return immediately
    if len(results) >= 3 and results[0]['score'] >= 0.9:
        return results[:limit]
    
    # PHASE 2: FAST - Query TMDB API (parallel to local results)
    try:
        tmdb_results = quick_tmdb_search(query, limit=5)
        
        # Merge with local results, avoiding duplicates
        for tmdb_result in tmdb_results:
            if tmdb_result['tmdb_id'] not in seen_ids:
                results.append(tmdb_result)
                seen_ids.add(tmdb_result['tmdb_id'])
        
        # Re-sort combined results
        results.sort(key=lambda x: x['score'], reverse=True)
        
    except Exception as e:
        print(f"TMDB autocomplete error: {e}")
    
    return results[:limit]

@lru_cache(maxsize=200)
def quick_tmdb_search(query, limit=5):
    """Cached TMDB search with timeout for speed"""
    search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
    
    try:
        resp = requests.get(search_url, timeout=1).json()
        results = []
        
        for item in resp.get('results', [])[:limit]:
            if item.get('media_type') not in ['movie', 'tv']:
                continue
                
            title = item.get('title') or item.get('name', '')
            year = (item.get('release_date') or item.get('first_air_date') or '')[:4]
            
            results.append({
                'title': title,
                'year': year,
                'tmdb_id': item['id'],
                'media_type': item['media_type'],
                'score': fuzzy_match_score(query, title),
                'source': 'tmdb'
            })
        
        return results
    except:
        return []

def smart_search_preprocess(query):
    """Enhanced preprocessing with instant local search"""
    clean_query = query.strip().lower()
    
    # Check exact aliases
    if clean_query in SEARCH_ALIASES:
        return SEARCH_ALIASES[clean_query], 1.0
    
    # Check local database
    for movie in POPULAR_TITLES_DB:
        if clean_query in movie['aliases']:
            return movie['title'], 1.0
        if clean_query == movie['title'].lower():
            return movie['title'], 1.0
        if fuzzy_match_score(query, movie['title']) > 0.85:
            return movie['title'], 0.9
    
    return query, 0

def search_tmdb_multi_strategy(query, region):
    """Multi-strategy search with caching"""
    preprocessed_query, confidence = smart_search_preprocess(query)
    
    search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={preprocessed_query}"
    
    try:
        resp = requests.get(search_url, timeout=5).json()
        results = [r for r in resp.get('results', []) if r.get('media_type') in ['movie', 'tv']]
        
        if results and confidence > 0.7:
            return results[0], results[0]['media_type']
        
        if results:
            for result in results[:5]:
                title = result.get('title') or result.get('name', '')
                if fuzzy_match_score(query, title) > 0.6:
                    return result, result['media_type']
            return results[0], results[0]['media_type']
        
    except Exception as e:
        print(f"Search API Error: {e}")
    
    # Fallback to original query
    if preprocessed_query != query:
        try:
            search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
            resp = requests.get(search_url, timeout=5).json()
            results = [r for r in resp.get('results', []) if r.get('media_type') in ['movie', 'tv']]
            if results:
                return results[0], results[0]['media_type']
        except:
            pass
    
    # Try year extraction
    year_match = re.search(r'\b(19|20)\d{2}\b', query)
    if year_match:
        query_without_year = query.replace(year_match.group(), '').strip()
        year = year_match.group()
        
        try:
            search_url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query_without_year}&year={year}"
            resp = requests.get(search_url, timeout=5).json()
            results = [r for r in resp.get('results', []) if r.get('media_type') in ['movie', 'tv']]
            if results:
                return results[0], results[0]['media_type']
        except:
            pass
    
    return None, None

def get_providers(tmdb_id, media_type, region):
    """Fetches streaming availability"""
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
    """Handles a single movie search"""
    poster_path = None
    release_date = "N/A"
    official_title = query

    if not tmdb_id:
        result, found_media_type = search_tmdb_multi_strategy(query, region)
        
        if not result:
            return None
        
        tmdb_id = result['id']
        media_type = found_media_type
        official_title = result.get('title') or result.get('name')
        release_date = result.get('release_date') or result.get('first_air_date') or "N/A"
        poster_path = result.get('poster_path')
    else:
        details_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}"
        try:
            first_hit = requests.get(details_url).json()
            official_title = first_hit.get('title') or first_hit.get('name')
            release_date = first_hit.get('release_date') or first_hit.get('first_air_date') or "N/A"
            poster_path = first_hit.get('poster_path')
        except:
            pass

    providers = get_providers(tmdb_id, media_type, region)
    processed_providers = []
    
    if providers:
        if 'flatrate' in providers:
            for p in providers['flatrate']:
                processed_providers.append({
                    'name': p['provider_name'],
                    'logo': f"https://image.tmdb.org/t/p/w92{p['logo_path']}",
                    'label': 'Subscription'
                })
        if 'rent' in providers:
            for p in providers['rent']:
                processed_providers.append({
                    'name': p['provider_name'],
                    'logo': f"https://image.tmdb.org/t/p/w92{p['logo_path']}",
                    'label': 'Rent'
                })
        if 'buy' in providers:
            for p in providers['buy']:
                if not any(x['name'] == p['provider_name'] for x in processed_providers):
                    processed_providers.append({
                        'name': p['provider_name'],
                        'logo': f"https://image.tmdb.org/t/p/w92{p['logo_path']}",
                        'label': 'Buy'
                    })

    if not processed_providers:
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

# === NEW ROUTE: INSTANT AUTOCOMPLETE API ===
@app.route('/api/autocomplete')
def autocomplete():
    """Lightning-fast autocomplete endpoint"""
    query = request.args.get('q', '')
    
    if len(query) < 2:
        return jsonify([])
    
    results = instant_autocomplete_search(query, limit=8)
    
    # Format for frontend
    suggestions = []
    for r in results:
        suggestions.append({
            'title': r['title'],
            'year': r['year'],
            'tmdb_id': r['tmdb_id'],
            'media_type': r['media_type'],
            'display': f"{r['title']} ({r['year']})"
        })
    
    return jsonify(suggestions)

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
                    if 'Name' in row:
                        titles.append(row['Name'])
                    elif 'Title' in row:
                        titles.append(row['Title'])
                
                titles = titles[:50]

                results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    future_to_title = {executor.submit(process_single_search, title, region): title for title in titles}
                    
                    for future in concurrent.futures.as_completed(future_to_title):
                        data = future.result()
                        if data:
                            results.append(data)

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