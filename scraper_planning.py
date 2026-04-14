        
# ── Standard Library ─────────────────────────────
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright

import firebase_admin
from firebase_admin import credentials, firestore


# =========================
# CONFIG
# =========================
URL = "https://anime-sama.to"
OUTPUT_DIR = Path("anime_planning_output")
OUTPUT_DIR.mkdir(exist_ok=True)


# =========================
# FIREBASE INIT (optionnel)
# =========================
try:
    cred = credentials.Certificate("credentials.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception:
    db = None


# =========================
# CLEAN + STRUCTURE
# =========================
def parse_element(raw_text):
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

    data = {
        "jour": None,
        "anime": None,
        "episode": None,
        "heure": None,
        "scraped_at": datetime.utcnow().isoformat()
    }

    if len(lines) >= 1:
        data["jour"] = lines[0]

    if len(lines) >= 2:
        data["anime"] = lines[1]

    if len(lines) >= 3:
        data["episode"] = lines[2]

    if len(lines) >= 4:
        data["heure"] = lines[3]

    return data


# =========================
# SCRAPING
# =========================
async def scrape_planning(page):
    print("📡 Chargement...")

    await page.goto(URL, wait_until="networkidle")

    # 🔥 laisse le JS charger
    await page.wait_for_timeout(3000)

    elements = await page.query_selector_all("div.fadeJours")

    print(f"🔎 {len(elements)} blocs trouvés")

    results = []

    for el in elements:
        try:
            raw_text = await el.inner_text()

            if not raw_text.strip():
                continue

            data = parse_element(raw_text)

            # nettoyage final (au cas où)
            for key in data:
                if isinstance(data[key], str):
                    data[key] = re.sub(r"\s+", " ", data[key]).strip()

            results.append(data)

        except Exception as e:
            print("⚠️ erreur:", e)

    return results


# =========================
# SAVE LOCAL
# =========================
def save_local(data):
    file = OUTPUT_DIR / "planning.json"

    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"💾 Sauvegardé: {file}")


# =========================
# SAVE FIREBASE
# =========================
def save_firebase(data):
    if db is None:
        print("⚠️ Firebase non actif")
        return

    try:
        # 🔥 on remplace tout (plus propre)
        batch = db.batch()

        for item in data:
            doc_ref = db.collection("anime_planning").document()
            batch.set(doc_ref, item)

        batch.commit()

        print("🔥 Firebase OK")

    except Exception as e:
        print("❌ Firebase erreur:", e)


# =========================
# MAIN
# =========================
async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        page = await browser.new_page()

        try:
            data = await scrape_planning(page)

            print(f"✅ {len(data)} éléments récupérés")

            save_local(data)
            save_firebase(data)

        except Exception as e:
            print("❌ ERREUR:", e)

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
