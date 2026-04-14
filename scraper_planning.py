        
                                import asyncio
import json
import aiohttp
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright
import firebase_admin
from firebase_admin import credentials, firestore


# ── FIREBASE ─────────────────────────

def init_firebase():
    if not firebase_admin._apps:
        cred = credentials.Certificate("serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
    return firestore.client()


# ── SAVE JSON ────────────────────────

def save_json(data, filename):
    Path("data").mkdir(exist_ok=True)
    with open(f"data/{filename}", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── EXTRACTION EPISODE (planning) ───

def extract_episode(text_list):
    for text in text_list:
        match = re.search(r"(?:ep|episode)\s*(\d+)", text.lower())
        if match:
            return int(match.group(1))
    return None


# ── SCRAPE PLANNING ─────────────────

async def scrape_planning(page):
    planning_data = []

    jours = await page.query_selector_all("div.fadeJours")

    for jour in jours:
        titre_elem = await jour.query_selector("h2.titreJours")
        jour_nom = (await titre_elem.inner_text()).strip()

        jour_data = {"jour": jour_nom, "animes": []}

        cartes = await jour.query_selector_all("div.anime-card-premium")

        for carte in cartes:
            titre = (await carte.query_selector(".card-title")).inner_text()
            titre = (await titre).strip()

            heure_elem = await carte.query_selector(".info-text.font-bold")
            heure = (await heure_elem.inner_text()).strip() if heure_elem else "?"

            infos = await carte.query_selector_all(".info-text")
            texts = [(await i.inner_text()).strip() for i in infos]

            # saison
            saison = next((t for t in texts if "saison" in t.lower()), "Inconnue")

            # épisode (🔥 ajout)
            episode_num = extract_episode(texts)

            # format
            badge_elem = await carte.query_selector(".badge-text")
            format_ = (await badge_elem.inner_text()).strip() if badge_elem else "?"

            # langue
            langues = []
            if await carte.query_selector('img[title="VF"]'):
                langues.append("VF")
            if await carte.query_selector('img[title="VOSTFR"]'):
                langues.append("VOSTFR")

            jour_data["animes"].append({
                "titre": titre,
                "heure": heure,
                "saison": saison,
                "episode": {
                    "numero": episode_num,
                    "label": f"EP {episode_num}" if episode_num else None
                },
                "format": format_,
                "langue": " & ".join(langues) if langues else "Inconnue"
            })

        planning_data.append(jour_data)

    return planning_data


# ── UPLOAD FIREBASE ─────────────────

def upload_planning(planning):
    db = init_firebase()

    doc_ref = db.collection("planning").document("weekly")

    doc_ref.set({
        "updated_at": datetime.utcnow().isoformat(),
        "jours": planning
    })

    print("🔥 Planning envoyé sur Firebase !")


# ── MAIN ────────────────────────────

async def main():
    url = "https://anime-sama.to/"

    async with aiohttp.ClientSession():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url)
            await page.wait_for_selector("div.fadeJours")

            planning = await scrape_planning(page)

            await browser.close()

    save_json(planning, "planning.json")
    upload_planning(planning)


if __name__ == "__main__":
    asyncio.run(main())
