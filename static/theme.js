// Theme toggle functionality
function toggleTheme() {
  const html = document.documentElement;
  const currentTheme = html.getAttribute('data-theme');
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
  
  html.setAttribute('data-theme', newTheme);
  localStorage.setItem('theme', newTheme);
  
  // Update button emoji
  const btn = document.querySelector('.theme-toggle');
  if (btn) {
    btn.textContent = newTheme === 'dark' ? '🌙' : '☀️';
  }
}

// Load saved theme on page load
document.addEventListener('DOMContentLoaded', function() {
  const savedTheme = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  
  const btn = document.querySelector('.theme-toggle');
  if (btn) {
    btn.textContent = savedTheme === 'dark' ? '🌙' : '☀️';
  }
});