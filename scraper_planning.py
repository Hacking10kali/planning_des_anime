"""
scraper_planning.py
-------------------
Scrape le planning hebdomadaire de anime-sama.to et l'envoie dans Firestore.

Structure Firestore :
  planning/{YYYY-MM-DD} -> {
    "jour":    "Lundi",
    "date":    "2026-04-06",
    "animes":  [ { ...infos..., "release_timestamp": <ISO 8601 UTC> } ]
  }

L'heure est stockee en UTC pur (timestamp ISO 8601).
Le client convertit selon son propre fuseau horaire.
"""

import asyncio
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import firebase_admin
from firebase_admin import credentials, firestore
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG — modifier uniquement cette section si le site change
# ══════════════════════════════════════════════════════════════════════════════

URL_BASE           = "https://anime-sama.to"   # <- changer ici si le domaine change
FIREBASE_CRED_PATH = Path(__file__).parent / "serviceAccountKey.json"
JIKAN_BASE         = "https://api.jikan.moe/v4"
JIKAN_DELAY        = 0.5   # secondes entre chaque appel Jikan (rate limit)


# ══════════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════════

_start = time.time()

def log(msg: str, level: str = "INFO"):
    elapsed = int(time.time() - _start)
    print(f"[{elapsed//60:02d}m{elapsed%60:02d}s][{level}] {msg}", flush=True)

def warn(msg): log(msg, "WARN")
def err(msg):  log(msg, "ERROR")


# ══════════════════════════════════════════════════════════════════════════════
#  FIREBASE
# ══════════════════════════════════════════════════════════════════════════════

def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(FIREBASE_CRED_PATH))
        firebase_admin.initialize_app(cred)
    return firestore.client()


def _firebase_retry(fn, retries=3):
    """Execute fn() avec backoff exponentiel en cas d'erreur Firebase."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            warn(f"Firebase erreur (tentative {attempt+1}/{retries}) : {e} — retry dans {wait}s")
            time.sleep(wait)


# ══════════════════════════════════════════════════════════════════════════════
#  MAPPING JOURS FR
# ══════════════════════════════════════════════════════════════════════════════

JOURS_FR = {
    "lundi":    0,
    "mardi":    1,
    "mercredi": 2,
    "jeudi":    3,
    "vendredi": 4,
    "samedi":   5,
    "dimanche": 6,
}


def next_weekday_date(jour_fr: str, reference: datetime):
    """
    Retourne la date correspondant au jour donne dans la semaine courante.
    `reference` doit etre en UTC.
    """
    jour_clean = jour_fr.strip().lower()
    jour_clean = (jour_clean
                  .replace("e", "e").replace("e", "e").replace("e", "e")
                  .replace("\u00e9", "e").replace("\u00e8", "e").replace("\u00ea", "e"))

    target_weekday = JOURS_FR.get(jour_clean)
    if target_weekday is None:
        warn(f"Jour inconnu : '{jour_fr}' (clean: '{jour_clean}')")
        return None

    today           = reference.date()
    current_weekday = today.weekday()   # lundi=0, dimanche=6
    delta           = target_weekday - current_weekday
    return today + timedelta(days=delta)


def build_utc_timestamp(date, heure_str: str):
    """
    Convertit une heure Paris (Europe/Paris) en timestamp UTC ISO 8601.
    Ex : date=2026-04-06, heure_str="18h30" -> "2026-04-06T16:30:00+00:00"
    """
    if not heure_str or heure_str.lower() in ("heure inconnue", "inconnu", ""):
        return None

    heure_str = re.sub(r"[hH]", ":", heure_str).strip()
    match = re.search(r"(\d{1,2}):(\d{2})", heure_str)
    if not match:
        return None

    hour, minute = int(match.group(1)), int(match.group(2))
    paris_tz = ZoneInfo("Europe/Paris")
    dt_paris = datetime(date.year, date.month, date.day, hour, minute, tzinfo=paris_tz)
    return dt_paris.astimezone(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════════════════════
#  IDs EXTERNES
# ══════════════════════════════════════════════════════════════════════════════

async def get_mal_id(session: aiohttp.ClientSession, titre: str):
    try:
        async with session.get(
            f"{JIKAN_BASE}/anime",
            params={"q": titre, "limit": 1},
            timeout=aiohttp.ClientTimeout(total=10)
        ) as resp:
            if resp.status != 200:
                return None
            data    = await resp.json()
            results = data.get("data", [])
            if results:
                mal_id = results[0].get("mal_id")
                log(f"MAL : {titre} -> {mal_id}")
                return mal_id
    except Exception as e:
        warn(f"Jikan erreur '{titre}' : {e}")
    return None


async def get_imdb_id(session: aiohttp.ClientSession, titre: str):
    try:
        query = titre.replace(" ", "_")
        url   = f"https://v2.sg.media-imdb.com/suggestion/x/{query}.json"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            for r in data.get("d", []):
                imdb_id = r.get("id", "")
                if imdb_id.startswith("tt"):
                    log(f"IMDB : {titre} -> {imdb_id}")
                    return imdb_id
    except Exception as e:
        warn(f"IMDB erreur '{titre}' : {e}")
    return None


async def resolve_ids(session: aiohttp.ClientSession, titre: str) -> dict:
    mal_id = await get_mal_id(session, titre)
    if mal_id:
        return {"mal_id": mal_id, "imdb_id": None}
    warn(f"MAL non trouve pour '{titre}', tentative IMDB...")
    imdb_id = await get_imdb_id(session, titre)
    return {"mal_id": None, "imdb_id": imdb_id}


# ══════════════════════════════════════════════════════════════════════════════
#  SCRAPING — Planning
# ══════════════════════════════════════════════════════════════════════════════

async def scrape_planning(page, session: aiohttp.ClientSession) -> list[dict]:
    log("Extraction du planning...")
    now_utc = datetime.now(timezone.utc)
    result  = []

    jours = await page.query_selector_all("div.fadeJours")
    log(f"{len(jours)} jour(s) trouve(s) dans le planning.")

    for jour_el in jours:
        titre_elem = await jour_el.query_selector("h2.titreJours")
        titre_jour = (await titre_elem.inner_text()).strip() if titre_elem else "Jour Inconnu"

        target_date = next_weekday_date(titre_jour, now_utc)
        date_iso    = target_date.isoformat() if target_date else None

        jour_entry = {
            "jour":   titre_jour,
            "date":   date_iso,
            "animes": [],
        }

        cartes = await jour_el.query_selector_all("div.anime-card-premium")
        for carte in cartes:
            titre_elem = await carte.query_selector(".card-title")
            titre      = (await titre_elem.inner_text()).strip() if titre_elem else "Titre Inconnu"

            heure_elem = await carte.query_selector(".info-text.font-bold")
            heure      = (await heure_elem.inner_text()).strip() if heure_elem else ""

            saison = "Saison Inconnue"
            for info in await carte.query_selector_all(".info-text"):
                cls = await info.get_attribute("class")
                if cls and "font-bold" not in cls:
                    saison = (await info.inner_text()).strip()
                    break

            badge_elem = await carte.query_selector(".badge-text")
            badge      = (await badge_elem.inner_text()).strip() if badge_elem else "Inconnu"

            langues = []
            if await carte.query_selector('img[title="VF"]'):     langues.append("VF")
            if await carte.query_selector('img[title="VOSTFR"]'): langues.append("VOSTFR")

            # Timestamp UTC
            release_timestamp = None
            if target_date and heure:
                release_timestamp = build_utc_timestamp(target_date, heure)

            # IDs
            ids = await resolve_ids(session, titre)
            await asyncio.sleep(JIKAN_DELAY)

            jour_entry["animes"].append({
                "titre":             titre,
                "heure_paris":       heure,
                "release_timestamp": release_timestamp,
                "saison":            saison,
                "format":            badge,
                "langue":            " & ".join(langues) if langues else "Inconnue",
                "mal_id":            ids["mal_id"],
                "imdb_id":           ids["imdb_id"],
            })

        log(f"{titre_jour} ({date_iso}) -> {len(jour_entry['animes'])} anime(s)")
        result.append(jour_entry)

    return result


# ══════════════════════════════════════════════════════════════════════════════
#  FIRESTORE UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_planning(db, planning: list[dict]) -> None:
    log("Upload vers Firestore...")
    planning_ref = db.collection("planning")

    for jour in planning:
        date_id = jour.get("date")
        if not date_id:
            warn(f"Pas de date pour '{jour['jour']}', ignore.")
            continue

        doc_data = {
            "jour":       jour["jour"],
            "date":       date_id,
            "animes":     jour["animes"],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        _firebase_retry(lambda: planning_ref.document(date_id).set(doc_data))
        log(f"planning/{date_id} -> {len(jour['animes'])} anime(s)")

    log("Upload termine.")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def main():
    db = init_firebase()
    log(f"START — URL_BASE = {URL_BASE}")

    async with aiohttp.ClientSession() as session:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="fr-FR",
                timezone_id="Europe/Paris",
            )

            page = await context.new_page()

            # Bloque les ressources inutiles pour accelerer le chargement
            await page.route(
                "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,ttf,mp4,mp3}",
                lambda r: r.abort()
            )

            # ── Chargement de la page avec fallback de strategies ─────────────
            log(f"Navigation vers {URL_BASE}/...")
            loaded = False
            for strategy in ("networkidle", "domcontentloaded", "load"):
                try:
                    await page.goto(
                        f"{URL_BASE}/",
                        wait_until=strategy,
                        timeout=60000
                    )
                    loaded = True
                    log(f"Page chargee (strategie: {strategy})")
                    break
                except Exception as e:
                    warn(f"Strategie '{strategy}' echouee : {e}")

            if not loaded:
                err("Impossible de charger la page apres toutes les strategies.")
                await browser.close()
                return

            # ── Attente du planning avec 3 tentatives ────────────────────────
            planning_found = False
            for attempt in range(3):
                try:
                    await page.wait_for_selector("div.fadeJours", timeout=30000)
                    planning_found = True
                    log("div.fadeJours trouve !")
                    break
                except PlaywrightTimeoutError:
                    warn(f"Tentative {attempt+1}/3 : div.fadeJours non trouve, attente 5s...")
                    await page.wait_for_timeout(5000)

            if not planning_found:
                # Dump HTML pour diagnostiquer ce qui est vraiment present
                html = await page.content()
                err("Planning introuvable apres 3 tentatives.")
                err(f"HTML snapshot (500 chars) : {html[:500]}")
                await browser.close()
                return

            planning = await scrape_planning(page, session)
            await browser.close()

    if planning:
        total_animes = sum(len(j["animes"]) for j in planning)
        log(f"{len(planning)} jour(s) | {total_animes} anime(s) scrapes")
        upload_planning(db, planning)
    else:
        warn("Aucune donnee de planning recuperee.")

    log("DONE.")


if __name__ == "__main__":
    asyncio.run(main())
