#!/usr/bin/env python3
"""
Script de diagnostic pour anime-sama
Analyse la structure de la page pour identifier les problèmes
"""

import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright

URL_BASE = "https://anime-sama.to"


async def diagnostic_complete(page):
    """Diagnostic complet de la page"""
    
    print("\n" + "="*80)
    print("🔍 DIAGNOSTIC ANIME-SAMA")
    print("="*80)
    
    # 1. Info de base
    print(f"\n📄 URL finale: {page.url}")
    print(f"📄 Titre: {await page.title()}")
    
    # 2. Attendre le chargement complet
    print("\n⏳ Attente du chargement...")
    await asyncio.sleep(5)
    
    # 3. Vérifier les sélecteurs principaux
    print("\n🎯 Test des sélecteurs:")
    selectors_to_test = [
        "div.fadeJours",
        "div.anime-card-premium",
        "h2.titreJours",
        ".card-title",
        '[class*="fade"]',
        '[class*="jour"]',
        '[class*="anime"]',
        '[class*="card"]',
    ]
    
    for selector in selectors_to_test:
        try:
            elements = await page.query_selector_all(selector)
            status = "✓" if len(elements) > 0 else "✗"
            print(f"  {status} {selector:30s} → {len(elements)} élément(s)")
        except Exception as e:
            print(f"  ✗ {selector:30s} → Erreur: {e}")
    
    # 4. Analyser toutes les classes CSS
    print("\n📋 Top 30 des classes CSS utilisées:")
    classes_info = await page.evaluate("""
        () => {
            const classCount = {};
            document.querySelectorAll('[class]').forEach(el => {
                el.className.split(' ').forEach(cls => {
                    if (cls.trim()) {
                        classCount[cls] = (classCount[cls] || 0) + 1;
                    }
                });
            });
            return Object.entries(classCount)
                .sort((a, b) => b[1] - a[1])
                .slice(0, 30)
                .map(([cls, count]) => ({class: cls, count}));
        }
    """)
    
    for idx, item in enumerate(classes_info, 1):
        print(f"  {idx:2d}. {item['class']:40s} ({item['count']} fois)")
    
    # 5. Chercher des divs avec "jour" ou "fade"
    print("\n🔎 Divs contenant 'jour', 'fade', ou 'planning':")
    relevant_divs = await page.evaluate("""
        () => {
            const keywords = ['jour', 'fade', 'planning', 'anime', 'card'];
            const divs = Array.from(document.querySelectorAll('div[class]'));
            
            return divs
                .filter(div => {
                    const className = div.className.toLowerCase();
                    return keywords.some(kw => className.includes(kw));
                })
                .slice(0, 20)
                .map(div => ({
                    class: div.className,
                    id: div.id || '',
                    children: div.children.length,
                    text_preview: div.innerText.substring(0, 60).replace(/\\n/g, ' ')
                }));
        }
    """)
    
    for idx, div in enumerate(relevant_divs, 1):
        print(f"\n  [{idx}] Classe: {div['class']}")
        if div['id']:
            print(f"      ID: {div['id']}")
        print(f"      Enfants: {div['children']}")
        print(f"      Texte: {div['text_preview']}...")
    
    # 6. Sauvegarder le HTML
    html_content = await page.content()
    filename = f"anime_sama_debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(html_content)
    print(f"\n💾 HTML complet sauvegardé: {filename}")
    
    # 7. Screenshot
    screenshot_file = filename.replace('.html', '.png')
    await page.screenshot(path=screenshot_file, full_page=True)
    print(f"📸 Screenshot sauvegardé: {screenshot_file}")
    
    # 8. Vérifier si du JavaScript charge du contenu
    print("\n⚙️  Test de chargement JavaScript:")
    
    # Observer les changements pendant 10 secondes
    initial_count = len(await page.query_selector_all('div'))
    print(f"  Divs initiaux: {initial_count}")
    
    for i in range(5):
        await asyncio.sleep(2)
        current_count = len(await page.query_selector_all('div'))
        if current_count != initial_count:
            print(f"  [+{i*2}s] Divs: {current_count} (changement détecté!)")
            initial_count = current_count
        else:
            print(f"  [+{i*2}s] Divs: {current_count} (stable)")
    
    # 9. Vérifier les requêtes réseau
    print("\n🌐 Informations réseau:")
    network_info = await page.evaluate("""
        () => {
            return {
                online: navigator.onLine,
                userAgent: navigator.userAgent.substring(0, 100)
            };
        }
    """)
    print(f"  En ligne: {network_info['online']}")
    print(f"  UserAgent: {network_info['userAgent']}...")
    
    print("\n" + "="*80)
    print("✓ Diagnostic terminé")
    print("="*80)


async def main():
    """Fonction principale"""
    async with async_playwright() as p:
        print(f"🚀 Lancement du diagnostic pour: {URL_BASE}\n")
        
        # Lancer le navigateur en mode visible pour voir ce qui se passe
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-setuid-sandbox']
        )
        
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        
        page = await context.new_page()
        
        # Activer la console
        page.on('console', lambda msg: print(f"  [CONSOLE] {msg.text}"))
        page.on('pageerror', lambda err: print(f"  [ERROR] {err}"))
        
        try:
            print(f"📡 Navigation vers {URL_BASE}...")
            response = await page.goto(URL_BASE, wait_until='domcontentloaded', timeout=45000)
            
            if response:
                print(f"✓ Réponse HTTP {response.status}")
                
                # Lancer le diagnostic
                await diagnostic_complete(page)
            else:
                print("✗ Pas de réponse HTTP")
                
        except Exception as e:
            print(f"\n❌ Erreur: {e}")
            
            # Essayer de sauvegarder quand même
            try:
                await page.screenshot(path='error.png')
                print("📸 Screenshot d'erreur sauvegardé: error.png")
            except:
                pass
        
        finally:
            await browser.close()
            print("\n👋 Navigateur fermé")


if __name__ == "__main__":
    asyncio.run(main())
