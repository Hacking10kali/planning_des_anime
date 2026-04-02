"""
scraper_planning.py
-------------------
Scrape le planning hebdomadaire de anime-sama.to et l'envoie dans Firestore.

Structure Firestore :
  planning/{YYYY-MM-DD} → {
    "jour":    "Lundi",
    "date":    "2026-04-06",
    "animes":  [ { ...infos..., "release_timestamp": <ISO 8601 UTC> } ]
  }

L'heure est stockée en UTC pur (timestamp ISO 8601).
Le client convertit selon son propre fuseau horaire.
"""

import asyncio
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import aiohttp
import firebase_admin
from firebase_admin import credentials, firestore
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ── Config Firebase ─────────────────────────────────────────────────────────────

FIREBASE_CRED_PATH = Path(__file__).parent / "serviceAccountKey.json"

def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate(str(FIREBASE_CRED_PATH))
        firebase_admin.initialize_app(cred)
    return firestore.client()


# ── Mapping jour FR → offset depuis aujourd'hui ─────────────────────────────────

JOURS_FR = {
    "lundi":    0,
    "mardi":    1,
    "mercredi": 2,
    "jeudi":    3,
    "vendredi": 4,
    "samedi":   5,
    "dimanche": 6,
}

def next_weekday_date(jour_fr: str, reference: datetime) -> datetime | None:
    """
    Retourne la prochaine date (ou date actuelle) correspondant au jour donné.
    `reference` doit être en UTC.
    On considère que le planning affiché = la semaine en cours (lundi à dimanche).
    """
    jour_clean = jour_fr.strip().lower()
    # Supprime les accents basiques
    jour_clean = jour_clean.replace("é", "e").replace("è", "e").replace("ê", "e")

    target_weekday = JOURS_FR.get(jour_clean)
    if target_weekday is None:
        return None

    # Lundi de la semaine courante
    today = reference.date()
    current_weekday = today.weekday()  # lundi=0, dimanche=6
    delta = target_weekday - current_weekday
    target_date = today + timedelta(days=delta)
    return target_date


def build_utc_timestamp(date, heure_str: str) -> str | None:
    """
    Convertit une heure Paris (Europe/Paris) en timestamp UTC ISO 8601.
    `date`      : datetime.date
    `heure_str` : "18:30" ou "18h30" etc.
    Retourne une chaîne ISO 8601 UTC, ex: "2026-04-06T16:30:00+00:00"
    """
    if not heure_str or heure_str.lower() in ("heure inconnue", "inconnu", ""):
        return None

    # Normalise "18h30" → "18:30"
    heure_str = re.sub(r"[hH]", ":", heure_str).strip()
    # Garde seulement HH:MM
    match = re.search(r"(\d{1,2}):(\d{2})", heure_str)
    if not match:
        return None

    hour, minute = int(match.group(1)), int(match.group(2))

    paris_tz = ZoneInfo("Europe/Paris")
    dt_paris = datetime(date.year, date.month, date.day, hour, minute, tzinfo=paris_tz)
    dt_utc = dt_paris.astimezone(timezone.utc)
    return dt_utc.isoformat()


# ── ID Lookup ───────────────────────────────────────────────────────────────────

async def get_mal_id(session: aiohttp.ClientSession, titre: str) -> int | None:
    try:
        url = "https://api.jikan.moe/v4/anime"
        params = {"q": titre, "limit": 1}
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
            results = data.get("data", [])
            if results:
                mal_id = results[0].get("mal_id")
                print(f"   ✅ MAL : {titre} → {mal_id}")
                return mal_id
    except Exception as e:
        print(f"   ⚠️  Jikan erreur '{titre}' : {e}")
    return None


async def get_imdb_id(session: aiohttp.ClientSession, titre: str) -> str | None:
    try:
        query = titre.replace(" ", "_")
        url = f"https://v2.sg.media-imdb.com/suggestion/x/{query}.json"
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            for r in data.get("d", []):
                imdb_id = r.get("id", "")
                if imdb_id.startswith("tt"):
                    print(f"   ✅ IMDB : {titre} → {imdb_id}")
                    return imdb_id
    except Exception as e:
        print(f"   ⚠️  IMDB erreur '{titre}' : {e}")
    return None


async def resolve_ids(session: aiohttp.ClientSession, titre: str) -> dict:
    mal_id = await get_mal_id(session, titre)
    if mal_id:
        return {"mal_id": mal_id, "imdb_id": None}
    print(f"   🔄 MAL non trouvé pour '{titre}', tentative IMDB...")
    imdb_id = await get_imdb_id(session, titre)
    return {"mal_id": None, "imdb_id": imdb_id}


# ── Scraping ────────────────────────────────────────────────────────────────────

async def scrape_planning(page, session: aiohttp.ClientSession) -> list[dict]:
    """
    Retourne une liste de jours :
    [
      {
        "jour":   "Lundi",
        "date":   "2026-04-06",          ← date ISO
        "animes": [ { ...champs... } ]
      },
      ...
    ]
    """
    print("\n📅 Extraction du planning...")
    now_utc = datetime.now(timezone.utc)
    result = []

    jours = await page.query_selector_all("div.fadeJours")
    for jour_el in jours:
        titre_elem = await jour_el.query_selector("h2.titreJours")
        titre_jour = (await titre_elem.inner_text()).strip() if titre_elem else "Jour Inconnu"

        target_date = next_weekday_date(titre_jour, now_utc)
        date_iso = target_date.isoformat() if target_date else None

        jour_entry = {
            "jour":   titre_jour,
            "date":   date_iso,
            "animes": [],
        }

        cartes = await jour_el.query_selector_all("div.anime-card-premium")
        for carte in cartes:
            titre_elem = await carte.query_selector(".card-title")
            titre = (await titre_elem.inner_text()).strip() if titre_elem else "Titre Inconnu"

            heure_elem = await carte.query_selector(".info-text.font-bold")
            heure = (await heure_elem.inner_text()).strip() if heure_elem else ""

            saison = "Saison Inconnue"
            for info in await carte.query_selector_all(".info-text"):
                cls = await info.get_attribute("class")
                if cls and "font-bold" not in cls:
                    saison = (await info.inner_text()).strip()
                    break

            badge_elem = await carte.query_selector(".badge-text")
            badge = (await badge_elem.inner_text()).strip() if badge_elem else "Inconnu"

            langues = []
            if await carte.query_selector('img[title="VF"]'):     langues.append("VF")
            if await carte.query_selector('img[title="VOSTFR"]'): langues.append("VOSTFR")

            # Timestamp UTC
            release_timestamp = None
            if target_date and heure:
                release_timestamp = build_utc_timestamp(target_date, heure)

            # IDs externes
            ids = await resolve_ids(session, titre)
            await asyncio.sleep(0.5)  # Jikan rate limit

            jour_entry["animes"].append({
                "titre":             titre,
                "heure_paris":       heure,          # gardé pour debug
                "release_timestamp": release_timestamp,  # UTC ISO 8601
                "saison":            saison,
                "format":            badge,
                "langue":            " & ".join(langues) if langues else "Inconnue",
                "mal_id":            ids["mal_id"],
                "imdb_id":           ids["imdb_id"],
            })

        total = len(jour_entry["animes"])
        print(f"   {titre_jour} ({date_iso}) → {total} anime(s)")
        result.append(jour_entry)

    return result


# ── Firestore Upload ────────────────────────────────────────────────────────────

def upload_planning(db, planning: list[dict]) -> None:
    """
    Écrit chaque jour dans planning/{YYYY-MM-DD}.
    Remplace le document existant (set avec merge=False).
    """
    print("\n🔥 Upload vers Firestore...")
    planning_ref = db.collection("planning")

    for jour in planning:
        date_id = jour.get("date")
        if not date_id:
            print(f"   ⚠️  Pas de date pour '{jour['jour']}', ignoré.")
            continue

        doc_data = {
            "jour":        jour["jour"],
            "date":        date_id,
            "animes":      jour["animes"],
            "updated_at":  datetime.now(timezone.utc).isoformat(),
        }

        planning_ref.document(date_id).set(doc_data)
        print(f"   ✅ planning/{date_id} → {len(jour['animes'])} anime(s)")

    print("🔥 Upload terminé.")


# ── Main ────────────────────────────────────────────────────────────────────────

async def main():
    db = init_firebase()

    async with aiohttp.ClientSession() as session:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
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
            print("🌐 Navigation vers anime-sama.to...")
            await page.goto("https://anime-sama.to/", wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector("div.fadeJours", timeout=15000)
            except PlaywrightTimeoutError:
                print("⚠️  Timeout : section planning non trouvée.")
                await browser.close()
                return

            planning = await scrape_planning(page, session)
            await browser.close()

    if planning:
        total_animes = sum(len(j["animes"]) for j in planning)
        print(f"\n📅 {len(planning)} jour(s) | {total_animes} anime(s) scrapés")
        upload_planning(db, planning)
    else:
        print("⚠️  Aucune donnée de planning récupérée.")


if __name__ == "__main__":
    asyncio.run(main())
