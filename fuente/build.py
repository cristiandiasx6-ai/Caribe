#!/usr/bin/env python3
"""Compila la demo de Caribe en un único HTML autocontenido.
   - Une part1 + part2 + part3
   - Sustituye __IMG_*__ por data URIs base64 (archivo final funciona offline)
   - Marca cada imagen para fallback si falta el asset
"""
import base64, pathlib, re, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE
PARTS = [HERE / 'part1_head.html', HERE / 'part2_html.html', HERE / 'part3_js.html']
OUT = HERE.parent / 'Caribe.html'

IMG_MAP = {
    '__IMG_CARNIVAL__': ROOT / 'assets' / 'vibra-carnaval.jpg',
    '__IMG_SAMANA__':   ROOT / 'assets' / 'vibra-samana.jpg',
    '__IMG_MANGU__':    ROOT / 'assets' / 'vibra-mangu.jpg',
    '__IMG_CAKE__':     ROOT / 'assets' / 'market-cake.jpg',
    '__IMG_IPHONE__':   ROOT / 'assets' / 'market-iphone.jpg',
    '__IMG_PICAPOLLO__': ROOT / 'assets' / 'biz-pica-pollo.jpg',
}

html = ''.join(p.read_text(encoding='utf-8') for p in PARTS)

missing = []
total_bytes = 0
embedded = 0
for key, path in IMG_MAP.items():
    if key not in html:
        continue  # el placeholder ya no se usa (p.ej. tras la purga de datos de demo)
    if path.exists():
        raw = path.read_bytes()
        total_bytes += len(raw)
        b64 = base64.b64encode(raw).decode('ascii')
        html = html.replace(key, f'data:image/jpeg;base64,{b64}')
        embedded += 1
    else:
        missing.append(str(path))
        html = html.replace(key, 'data:,')

OUT.write_text(html, encoding='utf-8')
size_kb = OUT.stat().st_size / 1024
print(f'OK  {OUT}  ({size_kb:.0f} KB)  · imágenes incrustadas: {embedded}  ({total_bytes/1024:.0f} KB de assets)')
if missing:
    print('AVISO: faltan imágenes (se usará fallback visual):', *missing, sep='\n  ')

# sanity checks: balance de etiquetas básicas y placeholders sin resolver
for token in ['__IMG_', 'TODO', '{{']:
    if token in html:
        print(f'AVISO: el token {token!r} sigue presente en la salida')
for a, b in [('<div', '</div>'), ('<section', '</section>')]:
    print(f'{a}: {html.count(a)}  vs  {b}: {html.count(b)}')
