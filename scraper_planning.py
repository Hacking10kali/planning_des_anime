        
import asyncio
import json
from playwright.async_api import async_playwright

URL = "https://anime-sama.to/planning"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        await page.goto(URL, timeout=60000)

        # attendre que la page charge
        await page.wait_for_selector("div.fadeJours", timeout=60000)

        jours = await page.query_selector_all("div.fadeJours")

        planning = []

        for jour in jours:
            jour_data = {}

            # nom du jour
            titre = await jour.query_selector("h2, h3")
            jour_nom = await titre.inner_text() if titre else "Inconnu"
            jour_data["jour"] = jour_nom

            jour_data["animes"] = []

            # récupérer TOUS les animes du jour
            animes = await jour.query_selector_all("div > div")

            for anime in animes:
                texte = await anime.inner_text()

                # nettoyage
                texte = texte.replace("\n", " ").strip()

                if not texte:
                    continue

                # extraction intelligente
                nom = texte
                episode = None
                langue = None

                # détecter épisode
                import re
                ep_match = re.search(r"[Ee]pisode\s*(\d+)", texte)
                if ep_match:
                    episode = ep_match.group(1)

                # détecter langue
                if "VOSTFR" in texte:
                    langue = "VOSTFR"
                elif "VF" in texte:
                    langue = "VF"

                jour_data["animes"].append({
                    "nom": nom,
                    "episode": episode,
                    "langue": langue
                })

            planning.append(jour_data)

        await browser.close()

        # sauvegarde propre (important pour ton problème de \n)
        with open("planning.json", "w", encoding="utf-8") as f:
            json.dump(planning, f, ensure_ascii=False, indent=2)

        print("✅ Planning récupéré proprement !")

asyncio.run(main())
