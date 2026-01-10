// === theme.js ===

// === THEME SWITCHER ===
function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    const btn = document.querySelector('.theme-btn');
    if (btn) btn.innerHTML = (theme === 'dark') ? '🌙' : '☀️';
}

function toggleTheme() {
    const current = localStorage.getItem('theme') || 'dark';
    setTheme(current === 'dark' ? 'light' : 'dark');
}

// === MODE SWITCHER (Search vs CSV) ===
function switchMode(mode) {
    const searchForm = document.getElementById('search-form');
    const csvForm = document.getElementById('csv-form');
    const searchBtn = document.getElementById('search-btn');
    const csvBtn = document.getElementById('csv-btn');

    if (!searchForm || !csvForm || !searchBtn || !csvBtn) return;

    searchForm.classList.add('hidden');
    csvForm.classList.add('hidden');
    searchBtn.classList.remove('active');
    csvBtn.classList.remove('active');

    if (mode === 'search') {
        searchForm.classList.remove('hidden');
        searchForm.style.display = 'flex';
        searchBtn.classList.add('active');
    } else {
        csvForm.classList.remove('hidden');
        csvForm.style.display = 'flex';
        csvBtn.classList.add('active');
    }
}

// === SCROLL TOP BUTTON ===
window.onscroll = function() {
    const btn = document.getElementById("scrollTop");
    if (btn) {
        if (document.body.scrollTop > 200 || document.documentElement.scrollTop > 200) {
            btn.classList.add("visible");
        } else {
            btn.classList.remove("visible");
        }
    }
};

function topFunction() {
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// === INSTANT AUTOCOMPLETE ===
let autocompleteTimeout;
let selectedIndex = -1;

function debounce(func, wait) {
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(autocompleteTimeout);
            func(...args);
        };
        clearTimeout(autocompleteTimeout);
        autocompleteTimeout = setTimeout(later, wait);
    };
}

async function performAutocomplete(query) {
    const autocompleteList = document.getElementById('autocomplete-list');
    
    if (query.length < 2) {
        autocompleteList.innerHTML = '';
        selectedIndex = -1;
        return;
    }

    try {
        const response = await fetch(`/api/autocomplete?q=${encodeURIComponent(query)}`);
        const suggestions = await response.json();

        if (suggestions.length === 0) {
            autocompleteList.innerHTML = '';
            return;
        }

        // Build autocomplete HTML
        let html = '';
        suggestions.forEach(item => {
            const typeBadge = item.media_type === 'movie' 
                ? '<span class="type-badge badge-movie">MOVIE</span>' 
                : '<span class="type-badge badge-tv">TV</span>';
            
            html += `
                <div class="autocomplete-item" 
                     data-title="${item.title}" 
                     data-tmdb-id="${item.tmdb_id}" 
                     data-media-type="${item.media_type}">
                    <strong>${item.title}</strong> 
                    <span style="color:var(--muted); font-size:0.85rem;">(${item.year})</span>
                    ${typeBadge}
                </div>
            `;
        });

        autocompleteList.innerHTML = html;

        // Add click handlers
        document.querySelectorAll('.autocomplete-item').forEach(item => {
            item.addEventListener('click', function() {
                document.getElementById('movie-search').value = this.dataset.title;
                document.getElementById('tmdb_id').value = this.dataset.tmdbId;
                document.getElementById('media_type').value = this.dataset.mediaType;
                autocompleteList.innerHTML = '';
                selectedIndex = -1;
            });
        });

    } catch (error) {
        console.error('Autocomplete error:', error);
        autocompleteList.innerHTML = '';
    }
}

const debouncedAutocomplete = debounce(performAutocomplete, 150);

function updateSelection(items) {
    items.forEach((item, index) => {
        if (index === selectedIndex) {
            item.classList.add('selected');
            item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        } else {
            item.classList.remove('selected');
        }
    });
}

// === INITIALIZATION ===
document.addEventListener('DOMContentLoaded', () => {
    // 1. Load saved theme
    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);
    
    // 2. Default to 'Search' mode
    if (document.getElementById('search-btn')) {
        switchMode('search');
    }

    // 3. Setup Autocomplete
    const searchInput = document.getElementById('movie-search');
    const autocompleteList = document.getElementById('autocomplete-list');

    if (searchInput && autocompleteList) {
        // Input event
        searchInput.addEventListener('input', (e) => {
            debouncedAutocomplete(e.target.value);
        });

        // Focus event
        searchInput.addEventListener('focus', (e) => {
            if (e.target.value.length >= 2) {
                debouncedAutocomplete(e.target.value);
            }
        });

        // Keyboard navigation
        searchInput.addEventListener('keydown', (e) => {
            const items = autocompleteList.querySelectorAll('.autocomplete-item');
            
            if (items.length === 0) return;

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
                updateSelection(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                selectedIndex = Math.max(selectedIndex - 1, -1);
                updateSelection(items);
            } else if (e.key === 'Enter' && selectedIndex >= 0) {
                e.preventDefault();
                items[selectedIndex].click();
            } else if (e.key === 'Escape') {
                autocompleteList.innerHTML = '';
                selectedIndex = -1;
            }
        });

        // Click outside to close
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#movie-search') && !e.target.closest('#autocomplete-list')) {
                autocompleteList.innerHTML = '';
                selectedIndex = -1;
            }
        });
    }
});