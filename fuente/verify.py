import asyncio, pathlib, sys
from playwright.async_api import async_playwright

OUT = pathlib.Path('/tmp/shots'); OUT.mkdir(exist_ok=True)
errors, warnings, checks = [], [], []

def ok(name): checks.append(name); print('  OK', name)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1680, 'height': 950}, device_scale_factor=1.6)
        await page.add_init_script("window.__CARIBE_QUIET__ = true")
        page.on('console', lambda m: (errors if m.type == 'error' else warnings).append(f'[{m.type}] {m.text}'))
        page.on('pageerror', lambda e: errors.append(f'[pageerror] {e}'))
        await page.goto('file:///home/claude/caribe/Caribe.html', wait_until='load', timeout=60000)
        await page.wait_for_timeout(900)

        async def shot(name): await page.screenshot(path=str(OUT / name))
        async def tab(page_id): await page.click('.tab[data-page="' + page_id + '"]'); await page.wait_for_timeout(350)

        # 1) Sin servidor (file://) → la app abre, sin gate de registro
        if await page.locator('#regOverlay').is_visible():
            errors.append('[reg] el overlay de registro debería estar oculto sin servidor')
        else: ok('sin servidor → la app abre sin gate')

        # 2) El HTML no contiene la identidad de demo
        # (el limpiador de perfiles viejos menciona @alexrd una vez a propósito)
        html = (await page.content()).replace("m.handle === '@alexrd' || m.name === 'Alex Rivera'", '')
        for bad in ['Alex Rivera', '@alexrd', 'Mamá', 'Parque Duarte', 'caribe.app']:
            if bad in html:
                errors.append('[identidad] texto de demo presente: ' + bad)
        ok('sin restos de identidad de demo en el HTML')

        # 3) Chats vacíos + badge oculto
        chat_txt = await page.locator('#chatList').inner_text()
        assert 'Aún no tienes chats' in chat_txt, 'chat list vacío esperado'
        bd = await page.locator('#badgeChats').evaluate("el => getComputedStyle(el).display")
        assert bd == 'none', 'badge debe estar oculto'
        ok('chats vacíos + badge oculto')
        await shot('01-chats-vacios.png')

        # 4) Publicar un estado → aparece en la lista (sin comentarios falsos)
        await tab('page-estados')
        est_txt = await page.locator('#statusList').inner_text()
        assert 'Nadie ha publicado un estado todavía' in est_txt
        await page.evaluate("""() => {
          const i = document.getElementById('statusText');
          i.value = 'Hoy es un buen día para probar Caribe 🌴';
          i.dispatchEvent(new Event('input', { bubbles: true }));
          document.getElementById('publishStatusBtn').click();
        }""")
        await page.wait_for_timeout(400)
        est_txt = await page.locator('#statusList').inner_text()
        assert 'Mi estado' in est_txt, est_txt
        ok('publicar estado funciona, sin comentarios inventados')
        await shot('02-estado-publicado.png')

        # 5) En vivo sin cuenta: no abre una transmisión "de mentira"; pide registrarse
        await page.click('#openLiveBtn')
        await page.wait_for_timeout(500)
        assert await page.locator('#liveScreen.open').count() == 0
        ok('en vivo sin cuenta no abre (el live real se prueba en qa_live.py)')

        # 6) Market vacío con CTA honesta
        await tab('page-market')
        mk = await page.locator('#marketGrid').inner_text()
        assert 'Aún no hay publicaciones en el Market' in mk
        ok('market vacío honesto')
        await shot('04-market-vacio.png')

        # 7) Negocios vacío
        await tab('page-negocios')
        bz = await page.locator('#bizList').inner_text()
        assert 'Aún no hay negocios en Caribe' in bz
        ok('negocios vacío honesto')
        await shot('05-negocios-vacio.png')

        # 8) Pedidos vacío
        await page.click('#openOrders'); await page.wait_for_timeout(350)
        od = await page.locator('#ordersList').inner_text()
        assert 'Aún no tienes pedidos' in od
        ok('pedidos vacío honesto')
        await shot('06-pedidos-vacio.png')
        await page.click('#sheetOrders [data-close-sheet]'); await page.wait_for_timeout(200)

        # 9) Llamadas vacío
        await tab('page-llamadas')
        cl = await page.locator('#callList').inner_text()
        assert 'Sin llamadas recientes' in cl
        ok('llamadas vacío honesto')
        await shot('07-llamadas-vacio.png')

        # 10) Vibra vacío con CTA de crear
        await tab('page-vibra')
        vb = await page.locator('#vibraFeed').inner_text()
        assert 'Aún no hay videos en Vibra' in vb or 'Sé la primera persona' in vb
        assert await page.locator('[data-vcta="create"]').count() >= 1
        ok('vibra vacío con CTA «Crear un Vibra»')
        await shot('08-vibra-vacio.png')

        # 11) Comunidad vacía
        await page.click('.vtab[data-vtab="comunidad"]')
        await page.wait_for_timeout(300)
        grid_children = await page.locator('#communityGrid').evaluate('el => el.children.length')
        empty_visible = await page.locator('#communityEmpty').is_visible()
        assert grid_children == 0 and empty_visible
        ok('comunidad vacía')
        await shot('09-comunidad-vacia.png')

        # 12) Perfil (me): identidad neutra hasta registrarse
        await page.click('#page-vibra .me-chip'); await page.wait_for_timeout(450)
        pn = await page.locator('#pfName').inner_text()
        assert pn == 'Tú', pn
        ok('perfil propio sin identidad inventada')
        await shot('10-perfil-me.png')
        await page.click('#profileClose'); await page.wait_for_timeout(250)

        # 13) Tema oscuro y vuelta
        await tab('page-chats')
        await page.click('#page-chats .more-btn'); await page.wait_for_timeout(250)
        await page.click('#page-chats [data-settings]'); await page.wait_for_timeout(400)
        await page.click('#setDarkRow'); await page.wait_for_timeout(400)
        th = await page.locator('#screen').evaluate("el => el.dataset.theme")
        assert th == 'dark', th
        ok('tema oscuro funciona')
        await page.click('#setDarkRow'); await page.wait_for_timeout(300)
        await page.click('#sheetSettings .sheet-close'); await page.wait_for_timeout(250)

        await browser.close()

asyncio.run(main())
print('— checks OK (esperados 13)')
print('— errores de consola:', len(errors))
for e in errors[:20]: print(' ', e)
print('— warnings:', len(warnings))
for w in warnings[:8]: print(' ', w)
sys.exit(1 if errors else 0)
