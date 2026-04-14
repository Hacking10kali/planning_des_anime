        
# ── Standard Library ─────────────────────────────

import asyncio
import json
import aiohttp
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

import firebase_admin
from firebase_admin import credentials, firestore


# =========================
# CONFIG
# =========================
URL = "https://anime-sama.to"  # adapte si besoin
OUTPUT_DIR = Path("anime_planning_output")
OUTPUT_DIR.mkdir(exist_ok=True)

# =========================
# FIREBASE INIT (optionnel)
# =========================
# ⚠️ Si tu n'as pas encore mis le fichier credentials.json,
# commente cette partie pour tester le scraping seul

try:
    cred = credentials.Certificate("credentials.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception:
    db = None


# =========================
# SCRAPING LOGIC
# =========================
async def scrape_planning(page):
    print("📡 Chargement de la page...")

    await page.goto(URL, wait_until="networkidle")

    # 🔥 important : laisser le JS finir
    await page.wait_for_timeout(3000)

    # ❌ NE PAS attendre visible (cause timeout)
    elements = await page.query_selector_all("div.fadeJours")

    print(f"🔎 Elements trouvés: {len(elements)}")

    results = []

    for el in elements:
        try:
            text = await el.inner_text()

            if not text.strip():
                continue

            results.append({
                "text": text.strip(),
                "scraped_at": datetime.utcnow().isoformat()
            })

        except Exception as e:
            print("⚠️ erreur élément:", e)

    return results


# =========================
# SAVE LOCAL
# =========================
def save_local(data):
    file = OUTPUT_DIR / "planning.json"

    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"💾 Sauvegardé localement: {file}")


# =========================
# FIREBASE SAVE
# =========================
def save_firebase(data):
    if db is None:
        print("⚠️ Firebase non initialisé, skip")
        return

    for item in data:
        db.collection("anime_planning").add(item)

    print("🔥 Données envoyées à Firebase")


# =========================
# MAIN
# =========================
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page()

        try:
            data = await scrape_planning(page)

            print(f"✅ Scraping terminé: {len(data)} items")

            save_local(data)
            save_firebase(data)

        except Exception as e:
            print("❌ ERREUR GLOBAL:", e)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
