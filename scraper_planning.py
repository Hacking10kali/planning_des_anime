        
import asyncio
import json
import re
from playwright.async_api import async_playwright

URL = "https://anime-sama.to/planning"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
        )

        page = await context.new_page()

        print("🚀 Chargement...")
        await page.goto(URL, timeout=60000)

        # attendre que tout charge
        await page.wait_for_load_state("networkidle")
        await page.wait_for_timeout(5000)

        # petit scroll (important sur ce site)
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(2000)

        print("🔍 Récupération des jours...")

        jours = await page.query_selector_all("div.fadeJours")

        # fallback si site change
        if not jours:
            print("⚠️ fallback activé")
            jours = await page.query_selector_all("div")

        planning = []

        for jour in jours:
            try:
                titre = await jour.query_selector("h2, h3")
                jour_nom = await titre.inner_text() if titre else "Inconnu"

                animes_data = []

                # récupérer TOUS les blocs enfants
                blocs = await jour.query_selector_all("div")

                for bloc in blocs:
                    texte = await bloc.inner_text()

                    texte = texte.replace("\n", " ").strip()

                    # ignorer contenu vide ou trop court
                    if len(texte) < 5:
                        continue

                    # extraction infos
                    episode = None
                    langue = None

                    ep_match = re.search(r"[Ee]pisode\s*(\d+)", texte)
                    if ep_match:
                        episode = ep_match.group(1)

                    if "VOSTFR" in texte:
                        langue = "VOSTFR"
                    elif "VF" in texte:
                        langue = "VF"

                    animes_data.append({
                        "titre": texte,
                        "episode": episode,
                        "langue": langue
                    })

                # éviter les jours vides
                if animes_data:
                    planning.append({
                        "jour": jour_nom,
                        "animes": animes_data
                    })

            except Exception as e:
                print("❌ erreur bloc:", e)

        await browser.close()

        # sauvegarde propre
        with open("planning.json", "w", encoding="utf-8") as f:
            json.dump(planning, f, ensure_ascii=False, indent=2)

        print("✅ Terminé proprement !")

# lancement
asyncio.run(main())
