"""QA del live: A transmite con cámara (falsa), B lo ve por WebRTC, chat, corazones, contador, cierre."""
import asyncio, pathlib
from playwright.async_api import async_playwright

OUT = pathlib.Path('/tmp/shots'); OUT.mkdir(exist_ok=True)
BASE = 'http://127.0.0.1:8123'
errors, failures = [], []

async def register(page, name, phone):
    await page.goto(BASE + '/', wait_until='load', timeout=60000)
    await page.wait_for_timeout(900)
    await page.fill('#regName', name)
    await page.select_option('#regCountry', 'República Dominicana')
    await page.fill('#regPhone', phone)
    await page.click('#regSubmit')
    await page.wait_for_timeout(1500)

async def video_info(page):
    return await page.evaluate("""async () => {
      const v = document.querySelector('#liveVideo');
      const t0 = v.currentTime; await new Promise(r => setTimeout(r, 900));
      return { w: v.videoWidth, h: v.videoHeight, ready: v.readyState, advancing: v.currentTime > t0, hasStream: !!v.srcObject };
    }""")

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
                                                '--disable-features=WebRtcHideLocalIpsWithMdns', '--autoplay-policy=no-user-gesture-required'])
        ctxs = [await browser.new_context(viewport={'width': 420, 'height': 860}, permissions=['camera', 'microphone']) for _ in range(2)]
        A, B = [await c.new_page() for c in ctxs]
        for page, tag in ((A, 'A'), (B, 'B')):
            page.on('console', lambda m, t=tag: errors.append(f'[{t}] {m.text[:160]}') if m.type == 'error' else None)
            page.on('pageerror', lambda e, t=tag: errors.append(f'[{t}][pageerror] {e}'))
        def check(name, cond):
            print(('  ✅ ' if cond else '  ❌ ') + name)
            if not cond: failures.append(name)

        print('— 1. Dos cuentas')
        await register(A, 'Ana Live', '809 555 2001')
        await register(B, 'Beto Live', '809 555 2002')
        await A.click('.tab[data-page="page-estados"]'); await B.click('.tab[data-page="page-estados"]')
        await A.wait_for_timeout(400)

        print('— 2. A empieza a transmitir')
        await A.click('#openLiveBtn')
        await A.wait_for_timeout(1500)
        check('pantalla de live abierta en A', await A.locator('#liveScreen.open').count() == 1)
        va = await video_info(A)
        check('A se ve a sí misma (cámara)', va['hasStream'] and va['w'] > 0)

        print('— 3. B ve el aviso y entra')
        await B.wait_for_timeout(1200)
        check('aviso «Ana está en vivo» en B', await B.locator('#liveNowList .live-now').count() == 1)
        await B.locator('#liveNowList .live-now').click()
        for _ in range(20):
            if await B.locator('#liveScreen.has-video').count(): break
            await B.wait_for_timeout(500)
        check('B recibe el video (WebRTC conectado)', await B.locator('#liveScreen.has-video').count() == 1)
        vb = await video_info(B)
        check('video de B con imagen real y avanzando', vb['w'] > 0 and vb['advancing'])
        await B.screenshot(path=str(OUT / '310-live-espectador.png'))
        await A.wait_for_timeout(400)
        check('A cuenta 1 espectador', (await A.locator('#liveViewers').inner_text()).strip() == '1')

        print('— 4. Chat y corazones')
        await B.fill('#liveInput', 'Qué chulo el live 🔥'); await B.click('#liveSendBtn')
        await A.wait_for_timeout(900)
        check('A lee el comentario de B', 'chulo' in await A.locator('#liveComments').inner_text())
        check('B ve su propio comentario', 'chulo' in await B.locator('#liveComments').inner_text())
        await A.fill('#liveInput', 'Gracias por entrar 🌴'); await A.click('#liveSendBtn')
        await B.wait_for_timeout(900)
        check('B lee el comentario de la anfitriona', 'Gracias por entrar' in await B.locator('#liveComments').inner_text())
        await B.click('#liveHeartBtn')
        await A.wait_for_timeout(700)
        check('A ve flotar los corazones de B', await A.locator('#liveScreen .float-heart').count() > 0)
        await A.screenshot(path=str(OUT / '311-live-anfitriona.png'))

        print('— 5. B sale y vuelve a entrar')
        await B.click('#closeLive'); await A.wait_for_timeout(900)
        check('A vuelve a 0 espectadores', (await A.locator('#liveViewers').inner_text()).strip() == '0')
        await B.wait_for_timeout(500)
        await B.locator('#liveNowList .live-now').click()
        for _ in range(20):
            if await B.locator('#liveScreen.has-video').count(): break
            await B.wait_for_timeout(500)
        check('B reconecta y vuelve a ver el video', (await video_info(B))['w'] > 0)

        print('— 6. A termina la transmisión')
        await A.click('#closeLive'); await B.wait_for_timeout(1200)
        check('B sale solo del live', await B.locator('#liveScreen.open').count() == 0)
        check('el aviso desaparece', await B.locator('#liveNowList .live-now').count() == 0)
        check('A también cerró', await A.locator('#liveScreen.open').count() == 0)

        await browser.close()
    print(f'\n== RESULTADO: {len(failures)} fallos · {len(errors)} errores de consola ==')
    for e in errors[:8]: print('  ', e)

asyncio.run(main())
