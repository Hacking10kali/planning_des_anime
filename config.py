"""
Configuration pour le scraper Anime-Sama
Modifiez ces valeurs selon votre environnement
"""

import os
from pathlib import Path

# URL du site à scraper
URL_BASE = os.getenv("ANIME_SAMA_URL", "https://anime-sama.to")

# Répertoire de sortie (relatif au script ou absolu)
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./anime_planning_output"))

# Paramètres du navigateur
HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
BROWSER_TIMEOUT = int(os.getenv("BROWSER_TIMEOUT", "45000"))  # millisecondes

# Paramètres d'attente
SELECTOR_TIMEOUT = int(os.getenv("SELECTOR_TIMEOUT", "15000"))  # millisecondes
STABILIZATION_DELAY = int(os.getenv("STABILIZATION_DELAY", "3"))  # secondes

# API Jikan (MyAnimeList)
JIKAN_API_URL = "https://api.jikan.moe/v4/anime"
JIKAN_RATE_LIMIT = float(os.getenv("JIKAN_RATE_LIMIT", "0.5"))  # secondes entre requêtes
JIKAN_TIMEOUT = int(os.getenv("JIKAN_TIMEOUT", "10"))  # secondes

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Sélecteurs CSS (en cas de changement de structure)
SELECTOR_JOURS = os.getenv("SELECTOR_JOURS", "div.fadeJours")
SELECTOR_TITRE_JOUR = os.getenv("SELECTOR_TITRE_JOUR", "h2.titreJours")
SELECTOR_ANIME_CARD = os.getenv("SELECTOR_ANIME_CARD", "div.anime-card-premium")
SELECTOR_CARD_TITLE = os.getenv("SELECTOR_CARD_TITLE", ".card-title")
SELECTOR_HEURE = os.getenv("SELECTOR_HEURE", ".info-text.font-bold")
SELECTOR_INFO_TEXT = os.getenv("SELECTOR_INFO_TEXT", ".info-text")
SELECTOR_BADGE = os.getenv("SELECTOR_BADGE", ".badge-text")

# User Agent
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Viewport
VIEWPORT_WIDTH = int(os.getenv("VIEWPORT_WIDTH", "1920"))
VIEWPORT_HEIGHT = int(os.getenv("VIEWPORT_HEIGHT", "1080"))

# Créer le répertoire de sortie
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
