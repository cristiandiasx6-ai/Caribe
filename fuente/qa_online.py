import asyncio, pathlib, sys
from playwright.async_api import async_playwright

OUT = pathlib.Path('/tmp/shots'); OUT.mkdir(exist_ok=True)
BASE = 'http://127.0.0.1:8123'
errors, failures = [], []

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=[
            '--use-fake-device-for-media-stream',
            '--use-fake-ui-for-media-stream',
        ])
        ctxA = await browser.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=1.4)
        ctxB = await browser.new_context(viewport={'width': 1280, 'height': 900}, device_scale_factor=1.4)
        A = await ctxA.new_page(); B = await ctxB.new_page()
        for page, tag in ((A, 'A'), (B, 'B')):
            page.on('console', lambda m, t=tag: errors.append(f'[{t}][{m.type}] {m.text[:150]}') if m.type == 'error' else None)
            page.on('pageerror', lambda e, t=tag: errors.append(f'[{t}][pageerror] {e}'))

        def check(name, cond):
            print(('  ✅ ' if cond else '  ❌ ') + name)
            if not cond: failures.append(name)

        print('— 1. Teléfono A: registro obligatorio al primer uso')
        await A.goto(BASE + '/', wait_until='load', timeout=60000)
        await A.wait_for_timeout(1200)
        check('overlay de registro visible', await A.locator('#regOverlay').is_visible())
        await A.screenshot(path=str(OUT / '231-registro.png'))

        print('— 2. A se registra (Génesis QA)')
        await A.fill('#regName', 'Génesis QA Uno')
        await A.select_option('#regCountry', 'República Dominicana')
        await A.fill('#regPhone', '809 555 0101')
        await A.click('#regSubmit')
        await A.wait_for_timeout(1500)
        check('overlay se oculta tras registrarse', not await A.locator('#regOverlay').is_visible())

        print('— 3. Teléfono B: registro obligatorio')
        await B.goto(BASE + '/', wait_until='load', timeout=60000)
        await B.wait_for_timeout(1200)
        check('overlay de registro visible en B', await B.locator('#regOverlay').is_visible())
        await B.fill('#regName', 'Alex QA Dos')
        await B.select_option('#regCountry', 'México')
        await B.fill('#regPhone', '55 5555 0102')
        await B.click('#regSubmit')
        await B.wait_for_timeout(1500)
        check('overlay se oculta en B', not await B.locator('#regOverlay').is_visible())

        print('— 4. B abre Nuevo chat y ve a A (usuario real)')
        await B.click('[data-moremenu="menu-chats"]'); await B.wait_for_timeout(250)
        await B.click('#btnNewChat'); await B.wait_for_timeout(1600)
        rows = await B.locator('#contactList [data-peer]').count()
        check('aparece 1+ usuario real en Nuevo chat', rows >= 1)
        txtB = await B.locator('#contactList').inner_text()
        check('B ve a «Génesis QA Uno»', 'Génesis QA Uno' in txtB)
        await B.screenshot(path=str(OUT / '232-nuevo-chat-real.png'))

        print('— 5. B abre el chat y envía un texto')
        await B.locator('#contactList [data-peer]', has_text='Génesis QA Uno').first.click()
        await B.wait_for_timeout(600)
        await B.fill('#msgInput', 'hola desde QA 👋')
        await B.click('#sendFab')
        await B.wait_for_timeout(800)
        check('B ve su propia burbuja', 'hola desde QA' in await B.locator('#messages').inner_text())

        print('— 6. A recibe el mensaje (sondeo servidor)')
        await A.wait_for_timeout(4500)
        convo = A.locator('#chatList [data-chat^="on-"]')
        n = await convo.count()
        check('A tiene el chat en línea en su lista', n >= 1)
        check('badge/preview actualizado en A', 'hola desde QA' in await A.locator('#chatList').inner_text())
        await A.locator('#chatList [data-chat^="on-"]').first.click()
        await A.wait_for_timeout(700)
        check('A ve el texto recibido', 'hola desde QA' in await A.locator('#messages').inner_text())
        await A.screenshot(path=str(OUT / '233-chat-en-linea.png'))

        print('— 7. A responde y B lo recibe')
        await A.fill('#msgInput', '¿qué lo qué? 🌴')
        await A.click('#sendFab')
        await B.wait_for_timeout(4500)
        check('B recibe la respuesta de A', '¿qué lo qué?' in await B.locator('#messages').inner_text())

        print('— 8. Recarga de A: sesión persiste + historial se ve')
        await A.reload(wait_until='load')
        await A.wait_for_timeout(2500)
        check('overlay NO reaparece al recargar', not await A.locator('#regOverlay').is_visible())
        await A.locator('#chatList [data-chat^="on-"]').first.click()
        await A.wait_for_timeout(700)
        artxt = await A.locator('#messages').inner_text()
        check('historial tras recarga contiene ambos mensajes', 'hola desde QA' in artxt and '¿qué lo qué?' in artxt)

        print('— 9. Micrófono real (dispositivo falso del sistema)')
        await A.click('#voiceNoteBtn, #micIcon', timeout=3000) if False else None
        # ruta real: botón del compositor (icono mic cuando el input está vacío)
        await A.fill('#msgInput', '')
        await A.click('#sendFab')   # input vacío → toggleRecording()
        await A.wait_for_timeout(400)
        check('panel de voz abierto', await A.locator('#voicePanel').is_visible())
        await A.wait_for_timeout(2300)
        await A.click('#vpSendBtn')
        await A.wait_for_timeout(1500)
        aud = await A.locator('#messages .chat-audio').count()
        check('burbuja con <audio controls> agregada', aud >= 1)
        await A.screenshot(path=str(OUT / '234-audio-real.png'))

        await browser.close()

    print()
    errs = [e for e in errors if 'ERR_FILE_NOT_FOUND' not in e]
    if errs:
        print(f'— consola/pageerror ({len(errs)}):')
        for e in errs[:10]: print('   ', e)
    print(f'== RESULTADO: {len(failures)} fallos · {len(errs)} errores de consola ==')
    sys.exit(1 if failures or errs else 0)

asyncio.run(main())
