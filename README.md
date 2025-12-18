# 🎬 BoxdStream

**Turn your Letterboxd lists into Weekend Plans.**

BoxdStream is a Flask-based web application that solves the "Streaming Chaos" problem. It takes movie/TV titles and instantly identifies which streaming service (Netflix, Prime, Hotstar, etc.) holds the rights in your specific region.

🔗 **Live Demo:** [https://boxdstream-2.onrender.com/]

## 🚀 Features
* **Real-Time Availability:** Fetches live streaming data for 20+ regions using the TMDB API.
* **Smart Search:** Includes a custom autocomplete engine with debounce logic to reduce API calls.
* **Batch Processing:** Uses Python `ThreadPoolExecutor` to process huge watchlists (50+ movies) in seconds concurrently.
* **Responsive UI:** Mobile-first design with Dark/Light mode and Service Filtering.

## 🛠️ Tech Stack
* **Backend:** Python, Flask, Gunicorn
* **Frontend:** HTML5, CSS3 (Variables/Flexbox), JavaScript (Vanilla)
* **API:** TMDB (The Movie Database)
* **Deployment:** Render (CI/CD pipeline via GitHub)