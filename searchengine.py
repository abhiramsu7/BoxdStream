import sqlite3
import requests
import time
import math
import threading
from datetime import datetime
from difflib import SequenceMatcher

# CONFIG
DB_NAME = "boxdstream.db"
TMDB_API_KEY = "5b421e05cad15891667ec28db3d9b9ac"

class SearchEngine:
    def __init__(self):
        self.conn = None
        self.setup_database()
        
        # Start Crawler in Background
        self.crawler_thread = threading.Thread(target=self.start_crawling_routine, daemon=True)
        self.crawler_thread.start()

    def get_db(self):
        # SQLite connections must be thread-local
        return sqlite3.connect(DB_NAME, check_same_thread=False)

    # ==========================================
    # 1. INDEXING (The Database Structure)
    # ==========================================
    def setup_database(self):
        """Creates the Search Index Table"""
        conn = self.get_db()
        cursor = conn.cursor()
        
        # We store minimal data needed for Search & Display
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS movies (
                tmdb_id INTEGER PRIMARY KEY,
                title TEXT,
                normalized_title TEXT,
                media_type TEXT,
                release_date TEXT,
                popularity REAL,
                poster_path TEXT,
                last_updated INTEGER
            )
        ''')
        # Create an Index on the Title for lightning-fast lookups
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_title ON movies(normalized_title)')
        conn.commit()
        conn.close()

    def add_to_index(self, item):
        """Adds or Updates a movie in the local index"""
        conn = self.get_db()
        cursor = conn.cursor()
        
        title = item.get('title') or item.get('name')
        if not title: return

        # Normalize title for better matching (lowercase, stripped)
        norm_title = title.lower().strip()
        
        # Extract data
        m_id = item['id']
        media_type = item.get('media_type', 'movie')
        date = item.get('release_date') or item.get('first_air_date') or "N/A"
        pop = item.get('popularity', 0)
        poster = item.get('poster_path')
        
        cursor.execute('''
            INSERT OR REPLACE INTO movies 
            (tmdb_id, title, normalized_title, media_type, release_date, popularity, poster_path, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (m_id, title, norm_title, media_type, date, pop, poster, int(time.time())))
        
        conn.commit()
        conn.close()

    # ==========================================
    # 2. CRAWLING (The Background Spider)
    # ==========================================
    def start_crawling_routine(self):
        """Fetches popular content periodically to keep index fresh"""
        print("🕷️  Crawler Started: Indexing the Multiverse...")
        
        while True:
            try:
                # 1. Crawl Trending (Day & Week)
                self.crawl_tmdb_endpoint("trending/all/day")
                self.crawl_tmdb_endpoint("trending/all/week")
                
                # 2. Crawl Popular Movies & TV
                self.crawl_tmdb_endpoint("movie/popular")
                self.crawl_tmdb_endpoint("tv/popular")
                
                # 3. Crawl Top Rated (Classic Optimization)
                self.crawl_tmdb_endpoint("movie/top_rated")
                
                print(f"✅ Crawler Sleep: Index updated at {datetime.now().strftime('%H:%M:%S')}")
                
                # Sleep for 6 hours before next full crawl
                time.sleep(21600) 
            except Exception as e:
                print(f"❌ Crawler Error: {e}")
                time.sleep(60)

    def crawl_tmdb_endpoint(self, endpoint):
        """Helper to fetch pages from TMDB and index them"""
        # We fetch 3 pages (approx 60 items) per endpoint to keep it fast
        for page in range(1, 4): 
            url = f"https://api.themoviedb.org/3/{endpoint}?api_key={TMDB_API_KEY}&page={page}"
            resp = requests.get(url).json()
            results = resp.get('results', [])
            
            for item in results:
                self.add_to_index(item)

    # ==========================================
    # 3. RANKING (The Google Algorithm)
    # ==========================================
    def search(self, query):
        """
        The Master Search Function:
        1. Checks Local Index (Fast)
        2. If low confidence, calls API (Fallback)
        3. Ranks results using Weighted Scoring
        """
        clean_query = query.lower().strip()
        conn = self.get_db()
        cursor = conn.cursor()
        
        # A. LOCAL SEARCH (SQL LIKE)
        # We look for partial matches in our crawled database
        cursor.execute("SELECT * FROM movies WHERE normalized_title LIKE ?", (f'%{clean_query}%',))
        rows = cursor.fetchall()
        conn.close()
        
        local_results = []
        for row in rows:
            local_results.append({
                "id": row[0],
                "title": row[1],
                "media_type": row[3],
                "release_date": row[4],
                "popularity": row[5],
                "poster_path": row[6]
            })

        # B. FALLBACK: If local index has < 3 results, HIT THE API
        # This ensures we never miss a niche movie that wasn't crawled
        if len(local_results) < 3:
            print(f"🌍 Index Miss: Fetching '{query}' from TMDB API...")
            api_results = self.fetch_from_api(query)
            # Merge API results into local_results
            for res in api_results:
                # Check if already exists to avoid duplicates
                if not any(x['id'] == res['id'] for x in local_results):
                    local_results.append(res)
                    # Add to index for NEXT time (Self-Healing Index)
                    self.add_to_index(res)

        # C. RANKING ALGORITHM
        ranked_results = self.rank_results(query, local_results)
        return ranked_results

    def fetch_from_api(self, query):
        """Direct API Hit (Fallback)"""
        url = f"https://api.themoviedb.org/3/search/multi?api_key={TMDB_API_KEY}&query={query}"
        resp = requests.get(url).json()
        valid = [x for x in resp.get('results', []) if x.get('media_type') in ['movie', 'tv']]
        return valid

    def rank_results(self, user_query, candidates):
        """
        Scores candidates based on:
        1. Text Similarity (60%)
        2. Popularity (30%)
        3. Exact Match Bonus (10%)
        """
        scored_candidates = []
        user_query_lower = user_query.lower()

        for item in candidates:
            title = item.get('title') or item.get('name')
            if not title: continue
            
            # 1. Text Score (Sequence Matcher)
            text_score = SequenceMatcher(None, user_query_lower, title.lower()).ratio()
            
            # 2. Popularity Score (Logarithmic Normalization)
            # Prevents super-popular unrelated movies from dominating
            pop = item.get('popularity', 0)
            pop_score = 0
            if pop > 0:
                pop_score = math.log(pop + 1) / 10 # Normalize roughly 0-1
                if pop_score > 1: pop_score = 1
            
            # 3. Exact Match Boost
            exact_bonus = 0.2 if title.lower() == user_query_lower else 0
            
            # 4. Final Weighted Score
            # Text is King (0.6), Popularity is Queen (0.3), Exact Match is the Ace (0.1)
            final_score = (text_score * 0.6) + (pop_score * 0.3) + exact_bonus
            
            item['search_score'] = final_score
            scored_candidates.append(item)

        # Sort by Score (High to Low)
        scored_candidates.sort(key=lambda x: x['search_score'], reverse=True)
        return scored_candidates

# Initialize Singleton
engine = SearchEngine()