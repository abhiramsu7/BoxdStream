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

// === MODE SWITCHER (Home Page) ===
// This function has been simplified as mode toggle buttons are removed for mobile.
function switchMode(mode) {
    // Get elements for the search and csv modes
    const searchForm = document.getElementById('search-form');
    const csvForm = document.getElementById('csv-form');
    const searchBtn = document.getElementById('search-btn');
    const csvBtn = document.getElementById('csv-btn');

    // Safety check: if any of these are null, we are likely on results page, so exit.
    if (!searchForm || !csvForm || !searchBtn || !csvBtn) return;

    // Hide both forms and remove active class from both buttons
    searchForm.classList.add('hidden');
    csvForm.classList.add('hidden');
    searchBtn.classList.remove('active');
    csvBtn.classList.remove('active');

    // Show the selected form and add active class to its button
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

// === INITIALIZATION (Load settings) ===
document.addEventListener('DOMContentLoaded', () => {
    // Set theme from storage or default
    const savedTheme = localStorage.getItem('theme') || 'dark';
    setTheme(savedTheme);
    
    // Default to search mode on load if we are on the home page
    if (document.getElementById('search-btn')) {
        switchMode('search');
    }
});