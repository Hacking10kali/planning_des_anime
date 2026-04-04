#!/usr/bin/env python3
"""
Scraper Anime-Sama Planning - Version GitHub Actions Compatible
================================================================
Version portable qui fonctionne dans n'importe quel environnement
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
import aiohttp
from playwright.async_api import async_playwright, Page

# Importer la configuration
try:
    from config import *
except ImportError:
    # Fallback si config.py n'existe pas
    from pathlib import Path
    import os
    
    URL_BASE = "https://anime-sama.to"
    OUTPUT_DIR = Path("./anime_planning_output")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    HEADLESS = True
    BROWSER_TIMEOUT = 45000
    SELECTOR_TIMEOUT = 15000
    STABILIZATION_DELAY = 3
    JIKAN_API_URL = "https://api.jikan.moe/v4/anime"
    JIKAN_RATE_LIMIT = 0.5
    JIKAN_TIMEOUT = 10
    LOG_LEVEL = "INFO"
    SELECTOR_JOURS = "div.fadeJours"
    SELECTOR_TITRE_JOUR = "h2.titreJours"
    SELECTOR_ANIME_CARD = "div.anime-card-premium"
    SELECTOR_CARD_TITLE = ".card-title"
    SELECTOR_HEURE = ".info-text.font-bold"
    SELECTOR_INFO_TEXT = ".info-text"
    SELECTOR_BADGE = ".badge-text"
    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    VIEWPORT_WIDTH = 1920
    VIEWPORT_HEIGHT = 1080

# Configuration du logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='[%(asctime)s][%(levelname)s] %(message)s',
    datefmt='%Mm%Ss'
)
logger = logging.getLogger(__name__)


async def resolve_ids(session: aiohttp.ClientSession, titre: str) -> Dict[str, Optional[str]]:
    """
    Résout les IDs MAL et IMDB pour un anime donné
    
    Args:
        session: Session aiohttp
        titre: Titre de l'anime
    
    Returns:
        Dict avec mal_id et imdb_id
    """
    ids = {"mal_id": None, "imdb_id": None}
    
    try:
        params = {"q": titre, "limit": 1}
        
        async with session.get(JIKAN_API_URL, params=params, timeout=JIKAN_TIMEOUT) as resp:
            if resp.status == 200:
                data = await resp.json()
                if data.get("data") and len(data["data"]) > 0:
                    anime = data["data"][0]
                    ids["mal_id"] = str(anime.get("mal_id"))
                    logger.debug(f"✓ MAL ID trouvé pour '{titre}': {ids['mal_id']}")
            else:
                logger.warning(f"Jikan API error {resp.status} pour '{titre}'")
                
    except asyncio.TimeoutError:
        logger.warning(f"Timeout lors de la recherche pour '{titre}'")
    except Exception as e:
        logger.warning(f"Erreur lors de la résolution des IDs pour '{titre}': {e}")
    
    return ids


async def scrape_planning_page(page: Page, session: aiohttp.ClientSession) -> List[Dict]:
    """
    Extrait le planning depuis la page
    
    Args:
        page: Page Playwright
        session: Session aiohttp pour les requêtes API
    
    Returns:
        Liste des jours avec leurs animes
    """
    logger.info("📅 Extraction du planning...")
    planning_data = []
    
    # Attendre que les éléments soient chargés avec plusieurs stratégies
    try:
        # Stratégie 1: Attendre le sélecteur principal
        logger.info(f"Attente de {SELECTOR_JOURS}...")
        await page.wait_for_selector(SELECTOR_JOURS, timeout=SELECTOR_TIMEOUT, state='visible')
        
        # Stratégie 2: Attendre que le contenu soit stable
        logger.info("Attente de stabilisation du contenu...")
        await asyncio.sleep(2)
        
        # Stratégie 3: Vérifier qu'on a au moins une carte
        await page.wait_for_selector(SELECTOR_ANIME_CARD, timeout=5000, state='visible')
        
    except Exception as e:
        logger.error(f"❌ Timeout en attendant le contenu dynamique: {e}")
        
        # Debug: Afficher les sélecteurs disponibles
        available_divs = await page.evaluate("""
            () => {
                const divs = Array.from(document.querySelectorAll('div[class]'));
                return divs.slice(0, 20).map(d => d.className);
            }
        """)
        logger.error(f"Classes div disponibles: {available_divs}")
        
        return []
    
    # Récupérer tous les jours
    jours = await page.query_selector_all(SELECTOR_JOURS)
    logger.info(f"✓ Trouvé {len(jours)} jour(s)")
    
    for idx, jour in enumerate(jours, 1):
        # Extraire le titre du jour
        titre_elem = await jour.query_selector(SELECTOR_TITRE_JOUR)
        titre_jour = (await titre_elem.inner_text()).strip() if titre_elem else "Jour Inconnu"
        
        logger.info(f"Traitement: {titre_jour}")
        
        jour_data = {
            "jour": titre_jour,
            "animes": []
        }
        
        # Récupérer toutes les cartes d'anime pour ce jour
        cartes = await jour.query_selector_all(SELECTOR_ANIME_CARD)
        logger.info(f"  → {len(cartes)} anime(s) trouvé(s)")
        
        for carte_idx, carte in enumerate(cartes, 1):
            try:
                # Extraire le titre
                titre_elem = await carte.query_selector(SELECTOR_CARD_TITLE)
                titre = (await titre_elem.inner_text()).strip() if titre_elem else "Titre Inconnu"
                
                # Extraire l'heure de sortie
                heure_elem = await carte.query_selector(SELECTOR_HEURE)
                heure = (await heure_elem.inner_text()).strip() if heure_elem else "Heure Inconnue"
                
                # Extraire la saison
                saison = "Saison Inconnue"
                info_elements = await carte.query_selector_all(SELECTOR_INFO_TEXT)
                for info in info_elements:
                    cls = await info.get_attribute("class")
                    if cls and "font-bold" not in cls:
                        saison = (await info.inner_text()).strip()
                        break
                
                # Extraire le format (badge)
                badge_elem = await carte.query_selector(SELECTOR_BADGE)
                badge = (await badge_elem.inner_text()).strip() if badge_elem else "Inconnu"
                
                # Extraire les langues disponibles
                langues = []
                if await carte.query_selector('img[title="VF"]'):
                    langues.append("VF")
                if await carte.query_selector('img[title="VOSTFR"]'):
                    langues.append("VOSTFR")
                
                # Résolution des IDs (avec rate limiting)
                ids = await resolve_ids(session, titre)
                await asyncio.sleep(JIKAN_RATE_LIMIT)
                
                # Ajouter l'anime au jour
                anime_data = {
                    "titre": titre,
                    "heure_sortie": heure,
                    "saison": saison,
                    "format": badge,
                    "langue": " & ".join(langues) if langues else "Inconnue",
                    "mal_id": ids["mal_id"],
                    "imdb_id": ids["imdb_id"],
                }
                
                jour_data["animes"].append(anime_data)
                logger.debug(f"    [{carte_idx}] {titre} - {heure} ({badge})")
                
            except Exception as e:
                logger.error(f"Erreur lors de l'extraction de la carte {carte_idx}: {e}")
                continue
        
        planning_data.append(jour_data)
    
    # Statistiques
    total_animes = sum(len(j["animes"]) for j in planning_data)
    logger.info(f"✓ Extraction terminée: {len(planning_data)} jour(s), {total_animes} anime(s)")
    
    return planning_data


async def save_planning_data(planning_data: List[Dict], format: str = "json"):
    """
    Sauvegarde les données du planning
    
    Args:
        planning_data: Données extraites
        format: Format de sortie (json, txt)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    if format == "json":
        # Sauvegarde JSON
        output_file = OUTPUT_DIR / f"planning_{timestamp}.json"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(planning_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"💾 Données sauvegardées: {output_file}")
        
    elif format == "txt":
        # Sauvegarde texte formaté
        output_file = OUTPUT_DIR / f"planning_{timestamp}.txt"
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("=" * 80 + "\n")
            f.write("PLANNING ANIME-SAMA\n")
            f.write(f"Généré le: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 80 + "\n\n")
            
            for jour in planning_data:
                f.write(f"\n{'─' * 80}\n")
                f.write(f"{jour['jour'].upper()}\n")
                f.write(f"{'─' * 80}\n\n")
                
                for anime in jour['animes']:
                    f.write(f"  📺 {anime['titre']}\n")
                    f.write(f"     ⏰ {anime['heure_sortie']}\n")
                    f.write(f"     📅 {anime['saison']}\n")
                    f.write(f"     🎬 {anime['format']}\n")
                    f.write(f"     🌐 {anime['langue']}\n")
                    if anime['mal_id']:
                        f.write(f"     🔗 MAL: https://myanimelist.net/anime/{anime['mal_id']}\n")
                    f.write("\n")
        
        logger.info(f"💾 Rapport texte sauvegardé: {output_file}")
    
    return output_file


async def main():
    """Fonction principale"""
    start_time = datetime.now()
    logger.info(f"🚀 START — URL_BASE = {URL_BASE}")
    logger.info(f"📁 OUTPUT_DIR = {OUTPUT_DIR.absolute()}")
    
    async with async_playwright() as p:
        # Lancer le navigateur
        logger.info("Lancement du navigateur Chromium...")
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        # Créer un contexte avec un user agent réaliste
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': VIEWPORT_WIDTH, 'height': VIEWPORT_HEIGHT}
        )
        
        page = await context.new_page()
        
        # Session HTTP pour les requêtes API
        async with aiohttp.ClientSession() as session:
            try:
                # Navigation vers la page
                logger.info(f"Navigation vers {URL_BASE}...")
                
                # Essayer différentes stratégies de chargement
                response = None
                strategies = ['domcontentloaded', 'networkidle']
                
                for strategy in strategies:
                    try:
                        logger.info(f"Tentative avec wait_until='{strategy}'...")
                        response = await page.goto(
                            URL_BASE, 
                            wait_until=strategy, 
                            timeout=BROWSER_TIMEOUT
                        )
                        if response and response.ok:
                            logger.info(f"✓ Page chargée avec '{strategy}' (status: {response.status})")
                            break
                    except Exception as e:
                        logger.warning(f"Échec avec '{strategy}': {e}")
                        if strategy == strategies[-1]:
                            raise
                
                # Attendre un peu pour le JavaScript
                logger.info(f"Attente de l'exécution JavaScript ({STABILIZATION_DELAY}s)...")
                await asyncio.sleep(STABILIZATION_DELAY)
                
                if response and response.ok:
                    # Vérifier la redirection
                    if page.url != URL_BASE:
                        logger.warning(f"Redirection: {URL_BASE} → {page.url}")
                    
                    # Extraire le planning
                    planning_data = await scrape_planning_page(page, session)
                    
                    if planning_data:
                        # Sauvegarder dans les deux formats
                        await save_planning_data(planning_data, "json")
                        await save_planning_data(planning_data, "txt")
                        
                        # Afficher un résumé
                        logger.info("\n" + "=" * 80)
                        logger.info("RÉSUMÉ DU PLANNING")
                        logger.info("=" * 80)
                        for jour in planning_data:
                            logger.info(f"{jour['jour']}: {len(jour['animes'])} anime(s)")
                        logger.info("=" * 80)
                    else:
                        logger.error("❌ Aucune donnée extraite")
                else:
                    logger.error(f"❌ Erreur HTTP: {response.status if response else 'No response'}")
                    
            except Exception as e:
                logger.error(f"❌ Erreur fatale: {e}", exc_info=True)
                
                # Sauvegarder un snapshot pour debug
                try:
                    screenshot = OUTPUT_DIR / "error_screenshot.png"
                    await page.screenshot(path=str(screenshot))
                    logger.info(f"📸 Screenshot sauvegardé: {screenshot}")
                    
                    html_snapshot = OUTPUT_DIR / "error_page.html"
                    content = await page.content()
                    with open(html_snapshot, 'w', encoding='utf-8') as f:
                        f.write(content)
                    logger.info(f"💾 HTML sauvegardé: {html_snapshot}")
                except:
                    pass
            
            finally:
                await browser.close()
    
    # Temps d'exécution
    duration = (datetime.now() - start_time).total_seconds()
    logger.info(f"✓ Terminé en {duration:.1f}s")


if __name__ == "__main__":
    asyncio.run(main())
