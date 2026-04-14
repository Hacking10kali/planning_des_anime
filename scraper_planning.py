import asyncio
import json
import aiohttp
import re
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError


# ── Utils ─────────────────────────────────────

def save_json(data, filename: str):
    output_dir = Path("data")
    output_dir.mkdir(exist_ok=True)
    path = output_dir / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 Sauvegardé : {path}")


# ── ID Lookup ─────────────────────────────────

async def get_mal_id(session, titre):
    try:
        url = "https://api.jikan.moe/v4/anime"
        params = {"q": titre, "limit": 1}
        async with session.get(url, params=params) as resp:
            data = await resp.json()
            results = data.get("data", [])
            if results:
                return results[0].get("mal_id")
    except:
        pass
    return None


async def get_imdb_id(session, titre):
    try:
        query = titre.replace(" ", "_")
        url = f"https://v2.sg.media-imdb.com/suggestion/x/{query}.json"
        async with session.get(url) as resp:
            data = await resp.json(content_type=None)
            for r in data.get("d", []):
                if r.get("id", "").startswith("tt"):
                    return r["id"]
    except:
        pass
    return None


async def resolve_ids(session, titre):
    mal_id = await get_mal_id(session, titre)
    if mal_id:
        return {"mal_id": mal_id, "imdb_id": None}

    imdb_id = await get_imdb_id(session, titre)
    return {"mal_id": None, "imdb_id": imdb_id}


# ── EXTRACTION EPISODE NUMBER (🔥 IMPORTANT) ──

async def extract_episode_number(ep_page):
    try:
        # 1. dans le title
        title = await ep_page.title()
        match = re.search(r"(?:ep|episode)\s*(\d+)", title.lower())
        if match:
            return int(match.group(1))

        # 2. dans le body
        body = await ep_page.inner_text("body")
        match = re.search(r"(?:ep|episode)\s*(\d+)", body.lower())
        if match:
            return int(match.group(1))

    except Exception as e:
        print(f"⚠️ erreur extraction épisode: {e}")

    return None


# ── SCRAPING RECENTS ─────────────────────────

async def scrape_recent_animes(page, context, session):
    print("\n🆕 Extraction des derniers épisodes...")
    recent_data = []

    container = await page.query_selector("#containerAjoutsAnimes")
    if not container:
        print("⚠️ introuvable")
        return recent_data

    cartes = await container.query_selector_all("div.anime-card-premium")

    for carte in cartes:
        lien_elem = await carte.query_selector("a")
        lien_url = await lien_elem.get_attribute("href") if lien_elem else None

        titre_elem = await carte.query_selector(".card-title")
        titre = (await titre_elem.inner_text()).strip()

        if lien_url and not lien_url.startswith("http"):
            lien_url = "https://anime-sama.to" + lien_url

        print(f"→ {titre}")

        episode_number = None
        lecteurs = []

        if lien_url:
            ep_page = await context.new_page()

            try:
                await ep_page.goto(lien_url, timeout=30000)

                # 🔥 EXTRACTION NUMERO
                episode_number = await extract_episode_number(ep_page)

                # lecteurs vidéo
                try:
                    await ep_page.wait_for_selector("#selectLecteurs", timeout=3000)

                    options = await ep_page.eval_on_selector_all(
                        "#selectLecteurs option",
                        "els => els.map(e => ({value: e.value, text: e.textContent.trim()}))"
                    )

                    for opt in options:
                        try:
                            await ep_page.select_option("#selectLecteurs", opt["value"])
                            await ep_page.wait_for_timeout(300)
                        except:
                            pass

                        iframe = await ep_page.query_selector("#playerDF")
                        src = await iframe.get_attribute("src") if iframe else None

                        lecteurs.append({
                            "nom": opt["text"],
                            "url": src
                        })

                except:
                    iframe = await ep_page.query_selector("#playerDF")
                    src = await iframe.get_attribute("src") if iframe else None
                    if src:
                        lecteurs.append({"nom": "defaut", "url": src})

            except Exception as e:
                print(f"⚠️ erreur page: {e}")

            finally:
                await ep_page.close()

        ids = await resolve_ids(session, titre)
        await asyncio.sleep(0.5)

        recent_data.append({
            "titre": titre,
            "episode_num": episode_number,  # 🔥 IMPORTANT
            "lien": lien_url,
            "lecteurs": lecteurs,
            "mal_id": ids["mal_id"],
            "imdb_id": ids["imdb_id"],
        })

    return recent_data


# ── MAIN ─────────────────────────────────────

async def main():
    url = "https://anime-sama.to/"

    async with aiohttp.ClientSession() as session:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()

            page = await context.new_page()
            await page.goto(url)

            await page.wait_for_selector("#containerAjoutsAnimes")

            recents = await scrape_recent_animes(page, context, session)

            await browser.close()

    save_json(recents, "episodes_recents.json")


if __name__ == "__main__":
    asyncio.run(main())
