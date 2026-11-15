# Caribe 🌴 — prueba multiusuario (código y app)

Mensajería estilo WhatsApp hecha en República Dominicana: registro obligatorio con
número + país + nombre, chat en línea entre amigos registrados, notas de voz y
fotos con el micrófono/cámara reales, PWA instalable. **Sin dependencias npm** (Node 22+ puro).

## Qué hay aquí

```
server.js          Servidor único: sirve la app (public/) y la API /api en el mismo origen
public/            La app (index.html ya construido, service worker, manifest, iconos)
fuente/            Código editable de la app (parts/*.html + build.py) y QA (qa_online, qa_voice, verify)
caribe.db          Base de datos SQLite (se crea sola al arrancar, en DATA_DIR). Arranca vacía.
package.json       npm start → node server.js
```

## Requisitos

- Node.js **22.13 o superior** (usa `node:sqlite`, incluido en Node). No hay que hacer `npm install`.
- Si vienes de la v2: el primer arranque importa tu `data.json` a la base y lo renombra a `data.json.migrado`. Los usuarios existentes deberán abrir la app una vez más para recibir su sesión.

## Correr en tu computadora (desarrollo local)

```bash
node server.js
# abre http://localhost:8123 en el teléfono/computadora de la MISMA red
```

Para probar en el teléfono **mic/cámara e instalación PWA requieren HTTPS**.
Lo más rápido para una prueba es un túnel (ej. `npx cloudflared tunnel --url http://localhost:8123`)
— el enlace generado sí permite permisos de cámara/mic e «Añadir a pantalla de inicio».

## Desplegar en internet (prueba permanente)

Cualquier host con Node 22+ sirve (Render, Fly.io, un VPS…). En Render (capa gratis):

1. Crea cuenta en render.com → **New → Web Service** → sube este proyecto (o conéctalo a un repo).
2. **Build Command:** *(vacío)* · **Start Command:** `node server.js`
3. En **Environment** añade `NODE_VERSION` = `22` (el archivo `.node-version` también lo indica).
4. Render asigna `PORT` automáticamente (el servidor ya lo lee) y publica en `https://<nombre>.onrender.com` — una URL fija, HTTPS, que permite mic/cámara e instalar la PWA en el teléfono.
5. Comparte ese enlace con tus amigos: cada quien abre, se registra (número + país + nombre) y ya pueden chatear 1 a 1.

> **Datos en el tier gratis:** el disco de Render es efímero; `caribe.db` se reinicia en cada redeploy/reinicio (los registros/mensajes se pierden). Para una prueba con amigos es aceptable; para conservar datos, monta un disco persistente o migra la API a una base de datos (PostgreSQL/SQLite) más adelante.

### Que los datos no se pierdan en Render

1. En el servicio: **Disks → Add Disk** (requiere plan de pago), *Mount Path* `/var/data`.
2. En **Environment** añade `DATA_DIR` = `/var/data`.
3. Redeploy. `caribe.db` ahora vive en el disco y sobrevive reinicios y redeploys.

En el plan gratis el servicio además se **duerme tras ~15 min sin tráfico** y tarda ~1 min en despertar: la app parece caída. Un monitor (p. ej. UptimeRobot) que pida `https://<tu-app>.onrender.com/api/health` cada 5 min lo mantiene despierto.

## Rendimiento y actualizaciones (v3.3)

- En el teléfono la app ocupa **toda la pantalla**: ya no dibuja una barra de estado ni un marco falsos (solo se ven en una computadora). Respeta la muesca y la barra de gestos con `env(safe-area-inset-*)`.
- El servidor envía la app **comprimida** (brotli/gzip: ~570 KB → ~115 KB) y con `ETag`, y el *service worker* la guarda en el teléfono: **abre al instante, incluso sin internet o con Render dormido**; luego se conecta.
- **Se actualiza sola:** el servidor pone en `sw.js` una huella del `index.html`; cada despliegue cambia la huella, el teléfono instala la versión nueva y recarga una vez (no interrumpe un live en curso). No hay que subir números de versión a mano.
- Si instalaste una versión anterior: ábrela una vez con internet; si el icono no cambia de aspecto, desinstálala y vuelve a instalarla una sola vez.

## Instalar en el teléfono (PWA)

Abre el enlace **https** en el navegador del teléfono:
- **Android (Chrome):** menú ⋮ → «Instalar app» / «Añadir a pantalla de inicio».
- **iPhone (Safari):** botón compartir → «Añadir a pantalla de inicio».

La app queda como un ícono más, a pantalla completa.

## Cómo funciona (para entender el código)

- **Registro obligatorio:** la app arranca mostrando la pantalla de registro; sin cuenta no hay chat. La cuenta (id + nombre + país + teléfono) vive en la base `caribe.db` del servidor.
- **Nuevo chat:** lista los usuarios REALES que se registraron en este servidor (`GET /api/users`). No hay contactos inventados.
- **Mensajes:** texto, imagen (dataURL, ≤5.5 MB) y audio (webm/opus). Los mensajes llegan al instante por **SSE** (`GET /api/stream`); el sondeo (`GET /api/messages?since=`) queda cada 20 s solo como respaldo. Todas las rutas (salvo `/api/health` y `/api/register`) exigen `Authorization: Bearer <token>`; el servidor ignora el remitente que diga el cliente y usa el de la sesión.
- **Mic/cámara:** `getUserMedia` de verdad; en segundo plano la onda del panel de voz se alimenta del `AnalyserNode`.
- **index.html es un artefacto único** (CSS/JS/imágenes incrustadas) generado por `fuente/build.py` a partir de `fuente/part*.html`. Si editas, edita `fuente/` y regenera (`python3 fuente/build.py` escribe `Caribe.html`; copia el resultado a `public/index.html`).
- **Vibra (feed) es real y compartido:** los Vibras (foto o texto, con producto opcional) se guardan en el servidor (`posts`, `likes`, `comments`, `follows`); las fotos se comprimen en el teléfono y se guardan como archivos en `DATA_DIR/media/`. Los me gusta, comentarios y nuevas publicaciones llegan a los demás al instante por SSE. Aún **no** se suben videos: un Vibra es foto o texto.
- **En vivo (Estados → «Ir en vivo»):** quien transmite abre su cámara; sus amigos con Caribe ven un aviso rojo «está en vivo», entran, comentan y mandan corazones/rosas en tiempo real.
- **No hay contenido de ejemplo.** Los listados (Vibra, Market, Negocios, Pedidos, Llamadas, Comunidad, Estados) arrancan vacíos por diseño; aparecen personas/productos reales cuando existan.

## QA / verificar que el build funciona

Requiere Python 3 + Playwright (`pip install playwright && playwright install chromium`):

```bash
python3 fuente/verify.py       # 13 chequeos del artefacto (offline, sin servidor)
python3 fuente/qa_online.py    # 2 "teléfonos" headless: registro, chat A↔B, historial, mic (16 chequeos)
python3 fuente/qa_voice.py     # panel de voz: grabar/pausar/descartar/enviar (14 chequeos)
python3 fuente/qa_feed.py      # Vibra real: publicar, tiempo real, like, comentar, seguir, persistencia (2 teléfonos)
python3 fuente/qa_live.py      # En vivo: transmitir, ver por WebRTC, chat, corazones, contador, cierre (2 teléfonos, cámara falsa)
```

## Límites conocidos (honestos) y próximos pasos

- Los videos cortos aún no existen (un Vibra es foto o texto).
- **En vivo:** el video va directo de teléfono a teléfono (WebRTC, malla P2P) y el servidor solo hace de señalización y chat. Máx. **8 espectadores** (quien transmite sube el video a cada uno). Necesita **HTTPS** (Render ya lo da) y cámara/micrófono permitidos. Con algunas redes móviles (CGNAT) la conexión directa puede fallar: para eso se añade un servidor TURN y se pasa al servidor con `TURN_URL`, `TURN_USER` y `TURN_PASS` (ej. `turn:mi-turn.example.com:3478`). Para cientos de espectadores hay que cambiar a LiveKit/SFU.
- Sin notificaciones push con la app cerrada (siguiente paso: Web Push / FCM).
- **Sin verificación por SMS:** quien conozca un número puede registrarse con él y tomar esa cuenta. Antes de abrirla al público hay que añadir un código OTP (Twilio u otro).
- Llamadas y «En vivo» público entre teléfonos aún **no existen** (fase experimental pendiente, WebRTC).
- El «Mi negocio» del panel es por ahora local al teléfono.
- Las fotos del feed viven en `DATA_DIR/media/` (hay que respaldarlas junto con `caribe.db`); las fotos y audios del chat siguen dentro de la base (≤5.5 MB c/u).
- Caribe.html servido directamente desde `file://` funciona como app offline de un solo jugador (sin chat en línea).
