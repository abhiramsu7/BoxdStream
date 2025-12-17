const toggle = document.getElementById("themeToggle");
if(toggle){
  toggle.onclick = () => {
    document.documentElement.dataset.theme =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  };
}

function showLoader(){
  const messages = [
    "Reading your watchlist…",
    "Matching titles with TMDB…",
    "Checking streaming platforms…",
    "Good taste ages better than streaming rights.",
    "Because watchlists deserve closure."
  ];
  let i = 0;
  setInterval(()=>{
    const el = document.getElementById("loaderText");
    if(el) el.textContent = messages[i++ % messages.length];
  }, 2500);

  document.getElementById("loader").classList.remove("hidden");
}
