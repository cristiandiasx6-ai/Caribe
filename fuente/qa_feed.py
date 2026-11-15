"""QA del feed de Vibra con 2 "teléfonos": publicar, ver en tiempo real, like, comentar, seguir, persistir."""
import asyncio, pathlib
from playwright.async_api import async_playwright

OUT = pathlib.Path('/tmp/shots'); OUT.mkdir(exist_ok=True)
BASE = 'http://127.0.0.1:8123'
errors, failures = [], []
# PNG 8x8 válido generado en el navegador (canvas) para no depender de archivos

async def register(page, name, phone):
    await page.goto(BASE + '/', wait_until='load', timeout=60000)
    await page.wait_for_timeout(900)
    await page.fill('#regName', name)
    await page.select_option('#regCountry', 'República Dominicana')
    await page.fill('#regPhone', phone)
    await page.click('#regSubmit')
    await page.wait_for_timeout(1500)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctxs = [await browser.new_context(viewport={'width': 420, 'height': 860}) for _ in range(2)]
        A, B = [await c.new_page() for c in ctxs]
        for page, tag in ((A, 'A'), (B, 'B')):
            page.on('console', lambda m, t=tag: errors.append(f'[{t}] {m.text[:160]}') if m.type == 'error' else None)
            page.on('pageerror', lambda e, t=tag: errors.append(f'[{t}][pageerror] {e}'))
        def check(name, cond):
            print(('  ✅ ' if cond else '  ❌ ') + name)
            if not cond: failures.append(name)

        print('— 1. Dos cuentas y feed vacío')
        await register(A, 'Ana Vibra', '809 555 1001')
        await register(B, 'Beto Vibra', '809 555 1002')
        await A.click('.tab[data-page="page-vibra"]'); await B.click('.tab[data-page="page-vibra"]')
        await A.wait_for_timeout(500)
        check('feed vacío muestra «Crear un Vibra»', await A.locator('#vibraFeed .pf-empty').count() == 1)

        print('— 2. A publica una foto con producto (ruta real de publicación)')
        await A.evaluate("""() => {
          const c = document.createElement('canvas'); c.width = 600; c.height = 900;
          const g = c.getContext('2d'); g.fillStyle = '#0f766e'; g.fillRect(0,0,600,900); g.fillStyle = '#fbbf24'; g.fillRect(100,300,400,300);
          return publishToServer({ caption: 'Bizcochos nuevos 🎂', text: '', img: c.toDataURL('image/png'), emoji: '🎂', grad: '', product: { name: 'Bizcocho 2 libras', price: 1300, emoji: '🎂' } });
        }""")
        await A.wait_for_timeout(1200)
        check('A ve su Vibra en el feed', await A.locator('#vibraFeed .slide').count() == 1)
        check('la foto se sirve desde /media', await A.evaluate("() => (document.querySelector('#vibraFeed .slide-bg')||{style:{}}).style.backgroundImage.includes('/media/')"))
        check('muestra el producto con precio', await A.locator('#vibraFeed .vibra-product').count() == 1)

        print('— 3. B lo recibe en tiempo real (sin recargar)')
        await B.wait_for_timeout(1200)
        check('B ve el Vibra de A', await B.locator('#vibraFeed .slide').count() == 1)
        check('autor correcto (@anavibra)', 'anavibra' in (await B.locator('#vibraFeed .vibra-handle').first.inner_text()).lower())

        print('— 4. B da like y A lo ve en vivo')
        await B.locator('#vibraFeed .like-btn').first.click()
        await B.wait_for_timeout(900)
        check('B: like marcado, contador 1', await B.locator('#vibraFeed .like-count').first.inner_text() == '1')
        await A.wait_for_timeout(500)
        check('A: contador sube a 1 sin recargar', await A.locator('#vibraFeed .like-count').first.inner_text() == '1')

        print('— 5. B comenta y A lo ve')
        await B.locator('#vibraFeed [data-action="comment"]').first.click()
        await B.wait_for_timeout(500)
        await B.fill('#commentInput', 'Se ve riquísimo 😋')
        await B.click('#sendCommentBtn')
        await B.wait_for_timeout(900)
        check('B: comentario aparece en la lista', 'riquísimo' in await B.locator('#commentsList').inner_text())
        await A.wait_for_timeout(400)
        check('A: contador de comentarios = 1', await A.locator('#vibraFeed .comment-count').first.inner_text() == '1')
        await A.locator('#vibraFeed [data-action="comment"]').first.click()
        await A.wait_for_timeout(700)
        check('A abre y lee el comentario de B', 'riquísimo' in await A.locator('#commentsList').inner_text())
        await A.screenshot(path=str(OUT / '300-comentarios.png'))

        print('— 6. B sigue a Ana; pestaña «Siguiendo»')
        await B.evaluate("() => document.querySelector('.sheet-backdrop, #sheetBackdrop') && 0")
        await B.keyboard.press('Escape')
        await B.evaluate("() => { if (typeof closeSheets === 'function') closeSheets(); }")
        await B.locator('#vibraFeed .rail-follow').first.click()
        await B.wait_for_timeout(600)
        await B.locator('#vibraTabs [data-vtab="siguiendo"]').click()
        await B.wait_for_timeout(400)
        check('Siguiendo muestra el Vibra de Ana', await B.locator('#vibraFeed .slide').count() == 1)

        print('— 7. Recargar B: todo persiste (estado en el servidor)')
        await B.reload(wait_until='load'); await B.wait_for_timeout(1800)
        await B.click('.tab[data-page="page-vibra"]'); await B.wait_for_timeout(500)
        check('Vibra sigue ahí tras recargar', await B.locator('#vibraFeed .slide').count() == 1)
        check('mi like se conserva', await B.locator('#vibraFeed .like-btn.liked').count() == 1)

        print('— 8. Vibra solo de texto')
        await B.evaluate("() => publishToServer({ caption: '', text: 'Hola desde La Vega 🌴', img: null, emoji: '✨', grad: 'linear-gradient(160deg,#134e4a,#0f766e)', product: null })")
        await B.wait_for_timeout(1000)
        await B.locator('#vibraTabs [data-vtab="para-ti"]').click(); await B.wait_for_timeout(300)
        check('aparece el Vibra de texto', await B.locator('#vibraFeed .vibra-textpost').count() == 1)
        await A.wait_for_timeout(500)
        check('A recibe 2 Vibras', await A.locator('#vibraFeed .slide').count() == 2)
        await B.screenshot(path=str(OUT / '301-feed.png'))

        await browser.close()
    print(f'\n== RESULTADO: {len(failures)} fallos · {len(errors)} errores de consola ==')
    for e in errors[:8]: print('  ', e)

asyncio.run(main())
