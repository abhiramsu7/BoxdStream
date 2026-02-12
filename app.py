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
import re 

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_flash_messages'

TMDB_API_KEY = "5b421e05cad15891667ec28db3d9b9ac"
MAX_WORKERS = 15 

session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

# ... (SEARCH_ALIASES and CUSTOM_METADATA hidden for brevity, keep your existing ones) ...
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

CUSTOM_METADATA = {
    "John Wick: Chapter 5": {
        "poster": "https://image.tmdb.org/t/p/original/tM9vBvLg4g4Vv7w4x9w4x9w4.jpg"
    }
}

def get_direct_link(provider_name, movie_title):
    clean_title = movie_title.split(':')[0].strip()
    clean_title = re.sub(r'[\(\)\-\–]', '', clean_title).strip()
    q = urllib.parse.quote(clean_title)
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
    url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={TMDB_API_KEY}&append_to_response=watch/providers,credits,videos&include_video_language=en,te,hi,ta,ml,kn"
    try:
        response = session.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
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

def get_trending():
    url = f"https://api.themoviedb.org/3/trending/all/day?api_key={TMDB_API_KEY}&language=en-US"
    try:
        resp = session.get(url).json()
        results = []
        for item in resp.get('results', [])[:10]:
            if item.get('media_type') not in ['movie', 'tv']: continue
            results.append({
                'title': item.get('title') or item.get('name'),
                'poster': f"https://image.tmdb.org/t/p/w500{item.get('poster_path')}" if item.get('poster_path') else None,
                'media_type': item.get('media_type'),
                'id': item.get('id')
            })
        return results
    except: return []

def smart_sort(results, user_query):
    scored_results = []
    user_query = user_query.lower().strip()
    for item in results:
        vote_score = item.get('vote_count', 0)
        lang = item.get('original_language', 'en')
        lang_boost = 0
        if lang in ['te', 'hi', 'ta', 'ml', 'kn']: lang_boost = 5000 
        title = item.get('title') or item.get('name') or ""
        match_boost = 0
        if title.lower().strip() == user_query: match_boost = 2000
        pop_score = item.get('popularity', 0)
        final_score = (vote_score * 2) + lang_boost + match_boost + pop_score
        item['smart_score'] = final_score
        scored_results.append(item)
    scored_results.sort(key=lambda x: x['smart_score'], reverse=True)
    return scored_results

def process_single_search(query, region, tmdb_id=None, media_type="movie", year=None, expand_collection=False):
    clean_query = query.strip().lower()
    if clean_query in SEARCH_ALIASES: final_query = SEARCH_ALIASES[clean_query]
    else: final_query = query

    movies_to_process = []
    if not tmdb_id:
        url = "https://api.themoviedb.org/3/search/multi"
        params = {"api_key": TMDB_API_KEY, "query": final_query, "include_adult": "false", "page": 1}
        try:
            resp = session.get(url, params=params).json()
            raw_results = [r for r in resp.get('results', []) if r.get('media_type') in ['movie', 'tv']]
            if raw_results:
                sorted_results = smart_sort(raw_results, final_query)
                first_hit = sorted_results[0]
                m_type = first_hit.get('media_type', 'movie')
                if m_type == 'movie' and expand_collection:
                    details_url = f"https://api.themoviedb.org/3/movie/{first_hit['id']}?api_key={TMDB_API_KEY}"
                    details = session.get(details_url).json()
                    collection = details.get('belongs_to_collection')
                    if collection:
                        parts = get_collection_parts(collection['id'])
                        for p in parts: p['media_type'] = 'movie' 
                        movies_to_process = parts
                    else: movies_to_process = [first_hit]
                else: movies_to_process = [first_hit]
            else: return [{ 'title': query, 'year': "Unknown", 'poster': None, 'providers': [], 'status': "Not Found", 'ui_class': "not-found", 'justwatch_link': "#" }]
        except: return [{ 'title': query, 'year': "Error", 'poster': None, 'providers': [], 'status': "Error", 'ui_class': "not-found", 'justwatch_link': "#" }]
    else:
        try:
            temp_hit = {'id': tmdb_id, 'media_type': media_type}
            if media_type == 'movie' and expand_collection:
                 details_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={TMDB_API_KEY}"
                 details = session.get(details_url).json()
                 collection = details.get('belongs_to_collection')
                 if collection:
                     parts = get_collection_parts(collection['id'])
                     for p in parts: p['media_type'] = 'movie' 
                     movies_to_process = parts
                 else: movies_to_process = [temp_hit]
            else: movies_to_process = [temp_hit]
        except: pass

    final_results = []
    for item in movies_to_process:
        m_id = item['id']
        m_type = item.get('media_type', 'movie')
        full_data = get_providers(m_id, m_type, region)
        if not full_data: continue

        m_title = full_data.get('title') or full_data.get('name')
        m_date = full_data.get('release_date') or full_data.get('first_air_date') or "N/A"
        m_poster = full_data.get('poster_path')
        m_overview = full_data.get('overview', 'No synopsis available.')
        
        seasons_count = None
        last_episode = None
        if m_type == 'tv':
            seasons_count = full_data.get('number_of_seasons')
            last_ep_data = full_data.get('last_episode_to_air')
            if last_ep_data: last_episode = f"S{last_ep_data.get('season_number')}E{last_ep_data.get('episode_number')}: {last_ep_data.get('name')}"
        
        poster_url = f"https://image.tmdb.org/t/p/w500{m_poster}" if m_poster else "https://via.placeholder.com/500x750?text=No+Poster"
        if m_title in CUSTOM_METADATA and not m_poster: poster_url = CUSTOM_METADATA[m_title]['poster']

        providers_data = full_data.get('watch/providers', {}).get('results', {}).get(region, {})
        processed_providers = []
        def add_provider(p_data, label):
            link = get_direct_link(p_data['provider_name'], m_title)
            return {'name': p_data['provider_name'], 'logo': f"https://image.tmdb.org/t/p/w92{p_data['logo_path']}", 'label': label, 'link': link}
        
        if 'flatrate' in providers_data: 
            for p in providers_data['flatrate']: processed_providers.append(add_provider(p, 'Subscription'))
        if 'rent' in providers_data: 
            for p in providers_data['rent']: processed_providers.append(add_provider(p, 'Rent'))
        if 'buy' in providers_data: 
            for p in providers_data['buy']: 
                if not any(x['name'] == p['provider_name'] for x in processed_providers): processed_providers.append(add_provider(p, 'Buy'))

        credits = full_data.get('credits', {})
        cast = [c['name'] for c in credits.get('cast', [])[:4]]
        crew = credits.get('crew', [])
        director = next((c['name'] for c in crew if c['job'] == 'Director' or c['job'] == 'Executive Producer'), "Unknown")
        
        videos = full_data.get('videos', {}).get('results', [])
        trailer_key = None
        teaser_key = None
        for v in videos:
            if v['site'] == 'YouTube':
                if v['type'] == 'Trailer': trailer_key = v['key']; break
                elif v['type'] == 'Teaser': teaser_key = v['key']
        final_video_key = trailer_key if trailer_key else teaser_key
        
        # === UPDATED STATUS LOGIC (28 DAYS) ===
        status = "Not Streaming"
        ui_class = "released-unknown"
        deep_links = [] 

        if processed_providers:
            status = "Streaming"
            ui_class = "streaming"
        else:
            is_future = False
            days_since_release = -1 
            if not m_date or m_date == "N/A": is_future = True
            else:
                try: 
                    release_obj = datetime.strptime(m_date, "%Y-%m-%d")
                    now = datetime.now()
                    if release_obj > now: is_future = True
                    else: days_since_release = (now - release_obj).days
                except: pass
            
            if is_future:
                status = "Coming Soon"
                ui_class = "unreleased"
                if not m_date or m_date == "N/A": m_date = "TBA"
            else:
                # 1. Theatrical Window: 0 to 28 Days
                if 0 <= days_since_release <= 28:
                    status = "In Theaters"
                    ui_class = "theatrical"
                
                # 2. Digital Release Window: 29 to 120 Days
                elif 28 < days_since_release <= 120:
                    status = "Digital Release Soon"
                    ui_class = "digital-release"
                    
                    # Generate ONE fallback link to JustWatch
                    q_enc = urllib.parse.quote(m_title)
                    deep_links = [
                        {'name': 'Check Status on JustWatch', 'url': f"https://www.justwatch.com/{region.lower()}/search?q={q_enc}",
                         'logo': 'https://www.themoviedb.org/assets/2/v4/logos/justwatch-c2e58adf5809b6871db650fb74b43db2b8f3637fe3709262572553fa056d8d0a.svg'}
                    ]
                
                # 3. Old Movies: 120+ Days
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
            'overview': m_overview,
            'cast': ", ".join(cast),
            'director': director,
            'trailer': final_video_key,
            'type': m_type,
            'seasons': seasons_count,
            'last_ep': last_episode,
            'deep_links': deep_links, # JustWatch Fallback
            'justwatch_link': f"https://www.justwatch.com/{region.lower()}/search?q={m_title}"
        })

    return final_results

# ... (Routes remain exactly the same) ...
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        mode = request.form.get('mode')
        region = request.form.get('region_code', 'IN')
        
        if mode == 'search':
            title = request.form.get('title')
            tmdb_id = request.form.get('tmdb_id')
            media_type = request.form.get('media_type')
            results = process_single_search(title, region, tmdb_id, media_type, expand_collection=True)
            
            if not results or results[0]['status'] == "Not Found":
                flash(f"Could not find results for '{title}'.", "error")
                return redirect(url_for('index'))
            
            active_providers = set()
            for r in results:
                for p in r['providers']:
                    p_name = p['name'].lower()
                    if 'netflix' in p_name: active_providers.add('netflix')
                    elif 'prime' in p_name: active_providers.add('prime')
                    elif 'apple' in p_name: active_providers.add('apple')
                    elif 'hotstar' in p_name: active_providers.add('hotstar')
                    elif 'zee5' in p_name: active_providers.add('zee5')
                    elif 'sony' in p_name: active_providers.add('sony')
                    elif 'aha' in p_name: active_providers.add('aha')
                    elif 'disney' in p_name: active_providers.add('disney')
                    elif 'hulu' in p_name: active_providers.add('hulu')

            return render_template('results.html', results=results, region=region, summary={}, active_providers=list(active_providers))

        elif mode == 'csv':
            if 'file' not in request.files: return redirect(url_for('index'))
            file = request.files['file']
            try:
                file_bytes = file.stream.read()
                try: text_data = file_bytes.decode('utf-8')
                except UnicodeDecodeError: text_data = file_bytes.decode('iso-8859-1')

                stream = io.StringIO(text_data, newline=None)
                csv_input = csv.DictReader(stream)
                
                tasks = []
                for row in csv_input:
                    name = row.get('Name') or row.get('Title')
                    year = row.get('Year') 
                    if name: tasks.append({'name': name, 'year': year})
                
                results = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                    future_to_task = {
                        executor.submit(process_single_search, t['name'], region, None, None, t['year'], False): t 
                        for t in tasks
                    }
                    for future in concurrent.futures.as_completed(future_to_task):
                        try:
                            data_list = future.result()
                            if data_list: results.extend(data_list)
                        except: pass

                def sort_key(x):
                    if x['status'] == 'Streaming': return 0
                    if x['status'] == 'In Theaters': return 1
                    if x['status'] == 'Digital Release Soon': return 1.5 
                    if x['status'] == 'Coming Soon': return 2
                    return 3
                unique_results = {v['title']+v['year']:v for v in results}.values()
                results = list(unique_results)
                results.sort(key=sort_key)

                active_providers = set()
                for r in results:
                    for p in r['providers']:
                        p_name = p['name'].lower()
                        if 'netflix' in p_name: active_providers.add('netflix')
                        elif 'prime' in p_name: active_providers.add('prime')
                        elif 'apple' in p_name: active_providers.add('apple')
                        elif 'hotstar' in p_name: active_providers.add('hotstar')
                        elif 'zee5' in p_name: active_providers.add('zee5')
                        elif 'sony' in p_name: active_providers.add('sony')
                        elif 'aha' in p_name: active_providers.add('aha')
                        elif 'disney' in p_name: active_providers.add('disney')
                        elif 'hulu' in p_name: active_providers.add('hulu')

                summary = {
                    'available_free': sum(1 for r in results if any(p['label'] == 'Subscription' for p in r['providers'])),
                    'rent_or_buy': sum(1 for r in results if any(p['label'] in ['Rent', 'Buy'] for p in r['providers'])),
                    'in_theaters': sum(1 for r in results if r['status'] == 'In Theaters'),
                    'not_streaming': sum(1 for r in results if r['status'] == 'Not Streaming'),
                    'unreleased': sum(1 for r in results if r['status'] == 'Coming Soon' or r['status'] == 'Not Found')
                }
                return render_template('results.html', results=results, region=region, summary=summary, active_providers=list(active_providers))
            except Exception as e:
                flash(f"CSV Error: {str(e)}", "error")
                return redirect(url_for('index'))

    trending_data = get_trending()
    return render_template('index.html', trending=trending_data)

@app.route('/api/autocomplete')
def autocomplete():
    query = request.args.get('q', '').strip().lower()
    if not query: return []
    final_query = query
    if query in SEARCH_ALIASES: final_query = SEARCH_ALIASES[query]
    url = "https://api.themoviedb.org/3/search/multi"
    params = { "api_key": TMDB_API_KEY, "query": final_query, "include_adult": "false", "language": "en-US", "page": 1 }
    try:
        resp = session.get(url, params=params).json()
        raw_results = [r for r in resp.get('results', []) if r.get('media_type') in ['movie', 'tv']]
        sorted_results = smart_sort(raw_results, final_query)
        clean_results = []
        for item in sorted_results[:10]: 
            title = item.get('title') or item.get('name')
            date = item.get('release_date') or item.get('first_air_date') or ""
            year = date.split('-')[0] if date else ""
            overview = item.get('overview', 'No detailed info available.')
            if len(overview) > 120: overview = overview[:120] + "..."
            clean_results.append({ "title": title, "year": year, "tmdb_id": item['id'], "media_type": item['media_type'], "overview": overview })
        return clean_results
    except Exception as e: return []

if __name__ == '__main__':
    app.run(debug=True)