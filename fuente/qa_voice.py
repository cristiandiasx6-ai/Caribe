import asyncio, pathlib
from playwright.async_api import async_playwright

OUT = pathlib.Path('/tmp/shots')
BASE = 'http://127.0.0.1:8123'
errors, warnings, results = [], [], []
def ok(name, cond): results.append((name, bool(cond))); print(('PASS' if cond else 'FAIL'), name)

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=[
            '--use-fake-device-for-media-stream',
            '--use-fake-ui-for-media-stream',
        ])
        ctxA = await browser.new_context(viewport={'width': 430, 'height': 900}, device_scale_factor=2)
        ctxB = await browser.new_context(viewport={'width': 430, 'height': 900}, device_scale_factor=2)
        A = await ctxA.new_page(); B = await ctxB.new_page()
        for page, tag in ((A, 'A'), (B, 'B')):
            page.on('console', lambda m, t=tag: (errors if m.type == 'error' else warnings).append(f'[{t}] {m.text[:150]}') if m.type == 'error' else (warnings.append(f'[{t}] {m.text[:150]}') if True else None))
            page.on('pageerror', lambda e, t=tag: errors.append(f'[{t}][pageerror] {e}'))
        await A.add_init_script("try{localStorage.setItem('caribe-theme','dark')}catch(e){}")

        # registro de A y B
        for page, name in ((A, 'Voz QA A'), (B, 'Voz QA B')):
            await page.goto(BASE + '/', wait_until='load', timeout=60000)
            await page.wait_for_timeout(1000)
            if await page.locator('#regOverlay').is_visible():
                await page.fill('#regName', name)
                await page.select_option('#regCountry', 'República Dominicana')
                await page.fill('#regPhone', '809 555 0301' if name.endswith('A') else '809 555 0302')
                await page.click('#regSubmit')
                await page.wait_for_timeout(1200)

        # A abre chat con B (Nuevo chat → usuario real registrado)
        await A.click('[data-moremenu="menu-chats"]'); await A.wait_for_timeout(250)
        await A.click('#btnNewChat'); await A.wait_for_timeout(1500)
        await A.locator('#contactList [data-peer]', has_text='Voz QA B').first.click()
        await A.wait_for_timeout(700)
        ok('Convo con el usuario real B abierta', await A.locator('#convoOverlay.open').count() == 1)

        before = await A.locator('#messages .bubble').count()
        await A.click('#sendFab'); await A.wait_for_timeout(300)
        ok('Panel visible al tocar mic', await A.locator('#voicePanel').is_visible())
        ok('Compositor oculto', not await A.locator('.composer').is_visible())
        ok('56 barras de onda', await A.locator('#vpWave .vp-bar').count() == 56)
        await A.wait_for_timeout(1800)
        t1 = (await A.locator('#vpTime').inner_text()).strip()
        ok('El timer avanza (%s)' % t1, t1 not in ('0:00', ''))
        heights = await A.evaluate("Array.from(document.querySelectorAll('#vpWave .vp-bar')).map(b => b.style.height)")
        ok('Onda animándose (alturas variadas: %d)' % len(set(heights)), len(set(heights)) >= 3)
        await A.screenshot(path=str(OUT / '230-voice-recording.png'))

        # pausa
        await A.click('#vpPauseBtn'); await A.wait_for_timeout(150)
        ok('Botón cambia a Reanudar', (await A.locator('#vpPauseLbl').inner_text()) == 'Reanudar')
        tp1 = (await A.locator('#vpTime').inner_text()).strip()
        await A.wait_for_timeout(1500)
        tp2 = (await A.locator('#vpTime').inner_text()).strip()
        ok('Timer congelado en pausa', tp1 == tp2)
        await A.screenshot(path=str(OUT / '231-voice-paused.png'))
        await A.click('#vpPauseBtn'); await A.wait_for_timeout(150)
        ok('Botón vuelve a Pausar', (await A.locator('#vpPauseLbl').inner_text()) == 'Pausar')

        # descartar
        await A.click('#vpCancelBtn'); await A.wait_for_timeout(300)
        ok('Panel oculto tras descartar', not await A.locator('#voicePanel').is_visible())
        ok('Compositor restaurado', await A.locator('.composer').is_visible())
        ok('Nada enviado al descartar', await A.locator('#messages .bubble').count() == before)

        # grabar y enviar
        await A.click('#sendFab'); await A.wait_for_timeout(1300)
        await A.click('#vpSendBtn'); await A.wait_for_timeout(900)
        after = await A.locator('#messages .bubble').count()
        ok('Audio enviado (burbuja nueva)', after == before + 1)
        audio_txt = await A.locator('#messages .bubble:last-child').inner_text()
        ok('Burbuja de audio con duración', 'Audio' in audio_txt)
        print('console errors:', errors or 'NONE')
        print('warnings:', len(warnings))
        failed = [n for n, c in results if not c]
        print('RESULT:', 'ALL PASS (%d)' % len(results) if not failed else f'{len(failed)} FAIL → {failed}')
        await browser.close()

asyncio.run(main())
