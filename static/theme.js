// === theme.js ===

// === THEME SWITCHER ===
function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    const btn = document.querySelector('.theme-btn');
    // Change icon based on theme
    if (btn) btn.innerHTML = (theme === 'dark') ? '🌙' : '☀️';
}

function toggleTheme() {
    const current = localStorage.getItem('theme') || 'dark';
    setTheme(current === 'dark' ? 'light' : 'dark');
}

// === MODE SWITCHER (Search vs CSV) ===
function switchMode(mode) {
    // Get the DOM elements
    const searchForm = document.getElementById('search-form');
    const csvForm = document.getElementById('csv-form');
    const searchBtn = document.getElementById('search-btn');
    const csvBtn = document.getElementById('csv-btn');

    // Safety check: if elements don't exist (e.g., on results page), stop.
    if (!searchForm || !csvForm || !searchBtn || !csvBtn) return;

    // Reset: Hide both forms and remove active class from buttons
    searchForm.classList.add('hidden');
    csvForm.classList.add('hidden');
    searchBtn.classList.remove('active');
    csvBtn.classList.remove('active');

    // Activate the selected mode
    if (mode === 'search') {
        searchForm.classList.remove('hidden');
        searchForm.style.display = 'flex'; // Ensure flex layout is restored
        searchBtn.classList.add('active');
    } else {
        csvForm.classList.remove('hidden');
        csvForm.style.display = 'flex'; // Ensure flex layout is restored
        csvBtn.classList.add('active');
    }
}

// === SCROLL TOP BUTTON (Results Page) ===
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

// === INITIALIZATION ===
document.addEventListener('DOMContentLoaded', () => {
    // 1. Load saved theme or default to dark
    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);
    
    // 2. Default to 'Search' mode if we are on the home page
    if (document.getElementById('search-btn')) {
        switchMode('search');
    }
});