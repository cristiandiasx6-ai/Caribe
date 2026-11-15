/* Caribe v3 — servidor único (Node 22+, sin dependencias npm)
   · Base de datos real: SQLite (node:sqlite) en DATA_DIR/caribe.db
   · Sesiones con token (el servidor ya no confía en el id que manda el cliente)
   · Tiempo real por SSE (/api/stream) — el sondeo queda solo como respaldo
   Uso: node server.js · PORT=3000 DATA_DIR=/var/data node server.js */
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const zlib = require('zlib');
const { DatabaseSync } = require('node:sqlite');

const PORT = process.env.PORT || 8123;
const ROOT = path.join(__dirname, 'public');
const DATA_DIR = process.env.DATA_DIR || __dirname;           // Render: apunta al disco persistente (ej. /var/data)
fs.mkdirSync(DATA_DIR, { recursive: true });
const MAX_BODY = 6 * 1024 * 1024;

/* ---------- base de datos ---------- */
const db = new DatabaseSync(path.join(DATA_DIR, 'caribe.db'));
db.exec(`
  PRAGMA journal_mode = WAL;
  CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL, dial TEXT NOT NULL, phone TEXT NOT NULL,
    created INTEGER NOT NULL, last_seen INTEGER NOT NULL, UNIQUE (dial, phone));
  CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), created INTEGER NOT NULL);
  CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY, from_id TEXT NOT NULL, to_id TEXT NOT NULL, kind TEXT NOT NULL,
    payload TEXT NOT NULL, dur REAL, ts INTEGER NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_msg_to ON messages (to_id, ts);
  CREATE INDEX IF NOT EXISTS idx_msg_from ON messages (from_id, ts);
  CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id),
    caption TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '', image TEXT, emoji TEXT, grad TEXT,
    product TEXT, ts INTEGER NOT NULL);
  CREATE TABLE IF NOT EXISTS likes (post_id INTEGER NOT NULL, user_id TEXT NOT NULL, PRIMARY KEY (post_id, user_id));
  CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER NOT NULL, user_id TEXT NOT NULL, text TEXT NOT NULL, ts INTEGER NOT NULL);
  CREATE INDEX IF NOT EXISTS idx_com_post ON comments (post_id, id);
  CREATE TABLE IF NOT EXISTS follows (follower_id TEXT NOT NULL, followee_id TEXT NOT NULL, PRIMARY KEY (follower_id, followee_id));
`);
const MEDIA_DIR = path.join(DATA_DIR, 'media');
fs.mkdirSync(MEDIA_DIR, { recursive: true });
const q = {
  userById:   db.prepare('SELECT * FROM users WHERE id = ?'),
  userByPhone:db.prepare('SELECT * FROM users WHERE dial = ? AND phone = ?'),
  insUser:    db.prepare('INSERT INTO users (id, name, country, dial, phone, created, last_seen) VALUES (?,?,?,?,?,?,?)'),
  updUser:    db.prepare('UPDATE users SET name = ?, country = ?, last_seen = ? WHERE id = ?'),
  seen:       db.prepare('UPDATE users SET last_seen = ? WHERE id = ?'),
  insSess:    db.prepare('INSERT INTO sessions (token_hash, user_id, created) VALUES (?,?,?)'),
  sessUser:   db.prepare('SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?'),
  allUsers:   db.prepare('SELECT * FROM users WHERE id != ? ORDER BY name'),
  insMsg:     db.prepare('INSERT INTO messages (id, from_id, to_id, kind, payload, dur, ts) VALUES (?,?,?,?,?,?,?)'),
  msgsSince:  db.prepare('SELECT * FROM messages WHERE (from_id = ? OR to_id = ?) AND ts > ? ORDER BY ts LIMIT 500'),
  prune:      db.prepare('DELETE FROM messages WHERE ts < (SELECT ts FROM messages ORDER BY ts DESC LIMIT 1 OFFSET 20000)'),
  feed:       db.prepare(`SELECT p.*, u.name AS author, u.country AS author_country,
                  (SELECT COUNT(*) FROM likes l WHERE l.post_id = p.id) AS likes,
                  (SELECT COUNT(*) FROM comments c WHERE c.post_id = p.id) AS comments,
                  EXISTS (SELECT 1 FROM likes l WHERE l.post_id = p.id AND l.user_id = ?) AS liked,
                  EXISTS (SELECT 1 FROM follows f WHERE f.follower_id = ? AND f.followee_id = p.user_id) AS following
                  FROM posts p JOIN users u ON u.id = p.user_id ORDER BY p.id DESC LIMIT 100`),
  insPost:    db.prepare('INSERT INTO posts (user_id, caption, text, image, emoji, grad, product, ts) VALUES (?,?,?,?,?,?,?,?)'),
  postById:   db.prepare('SELECT id, user_id FROM posts WHERE id = ?'),
  addLike:    db.prepare('INSERT OR IGNORE INTO likes (post_id, user_id) VALUES (?,?)'),
  delLike:    db.prepare('DELETE FROM likes WHERE post_id = ? AND user_id = ?'),
  likeCount:  db.prepare('SELECT COUNT(*) AS n FROM likes WHERE post_id = ?'),
  insCom:     db.prepare('INSERT INTO comments (post_id, user_id, text, ts) VALUES (?,?,?,?)'),
  comList:    db.prepare('SELECT c.id, c.text, c.ts, c.user_id, u.name FROM comments c JOIN users u ON u.id = c.user_id WHERE c.post_id = ? ORDER BY c.id DESC LIMIT 200'),
  comCount:   db.prepare('SELECT COUNT(*) AS n FROM comments WHERE post_id = ?'),
  addFollow:  db.prepare('INSERT OR IGNORE INTO follows (follower_id, followee_id) VALUES (?,?)'),
  delFollow:  db.prepare('DELETE FROM follows WHERE follower_id = ? AND followee_id = ?'),
  counts:     db.prepare('SELECT (SELECT COUNT(*) FROM users) AS users, (SELECT COUNT(*) FROM messages) AS messages'),
};
const newId = () => crypto.randomBytes(9).toString('hex');
const now = () => Date.now();
const hash = t => crypto.createHash('sha256').update(t).digest('hex');

/* migración única desde el data.json de la v2 */
(function migrate() {
  const old = [path.join(DATA_DIR, 'data.json'), path.join(__dirname, 'data.json')].find(f => fs.existsSync(f));
  if (!old || q.counts.get().users > 0) return;
  try {
    const raw = JSON.parse(fs.readFileSync(old, 'utf8'));
    if (!(raw.users || []).length) return;
    db.exec('BEGIN');
    for (const u of raw.users) q.insUser.run(u.id, u.name, u.country, u.dial, u.phone, u.created || now(), u.lastSeen || now());
    for (const m of raw.messages || []) q.insMsg.run(m.id, m.from, m.to, m.kind || 'text', m.payload || '', m.dur || null, m.ts || now());
    db.exec('COMMIT');
    fs.renameSync(old, old + '.migrado');
    console.log('Migrados', raw.users.length, 'usuarios desde', old);
  } catch (e) { try { db.exec('ROLLBACK'); } catch (_) {} console.error('migración', e); }
})();

/* ---------- utilidades ---------- */
const online = new Map();       // userId -> ts del último ping
const streams = new Map();      // userId -> Set(res) conexiones SSE abiertas
const isOnline = u => streams.has(u.id) || (now() - (online.get(u.id) || u.last_seen || 0)) < 120000;
const pubUser = u => ({ id: u.id, name: u.name, country: u.country, dial: u.dial, phone: u.phone });
const msgOut = m => ({ id: m.id, from: m.from_id, to: m.to_id, kind: m.kind, payload: m.payload, dur: m.dur == null ? undefined : m.dur, ts: m.ts });

function sendJson(res, code, obj) {
  res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(obj));
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on('data', c => { size += c.length; if (size > MAX_BODY) { reject(new Error('too big')); req.destroy(); return; } chunks.push(c); });
    req.on('end', () => { try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')); } catch (e) { reject(e); } });
    req.on('error', reject);
  });
}
function authUser(req, url) {
  const h = req.headers.authorization || '';
  const token = h.startsWith('Bearer ') ? h.slice(7) : (url.searchParams.get('t') || '');
  return token ? q.sessUser.get(hash(token)) : undefined;
}
function push(userId, event, data) {
  const set = streams.get(userId);
  if (!set) return;
  const frame = 'event: ' + event + '\ndata: ' + JSON.stringify(data) + '\n\n';
  for (const r of set) r.write(frame);
}
function broadcast(event, data) { for (const id of streams.keys()) push(id, event, data); }
/* guarda una imagen dataURL (jpeg/png/webp, ≤4 MB) como archivo y devuelve su nombre */
function saveImage(dataUrl) {
  const m = /^data:image\/(jpeg|png|webp);base64,([A-Za-z0-9+/=]+)$/.exec(String(dataUrl || ''));
  if (!m) return null;
  const buf = Buffer.from(m[2], 'base64');
  if (!buf.length || buf.length > 4 * 1024 * 1024) return null;
  const name = crypto.randomBytes(12).toString('hex') + '.' + (m[1] === 'jpeg' ? 'jpg' : m[1]);
  fs.writeFileSync(path.join(MEDIA_DIR, name), buf);
  return name;
}
const postOut = p => ({
  id: p.id, userId: p.user_id, author: p.author, country: p.author_country, caption: p.caption, text: p.text,
  img: p.image ? '/media/' + p.image : null, emoji: p.emoji, grad: p.grad,
  product: p.product ? JSON.parse(p.product) : null, ts: p.ts,
  likes: p.likes, comments: p.comments, liked: !!p.liked, following: !!p.following,
});
/* ---------- LIVE (video entre teléfonos por WebRTC; el servidor solo hace de señalización y chat) ---------- */
const lives = new Map();                 // hostId -> { title, name, since, viewers:Set<userId> }
const MAX_VIEWERS = 8;                   // malla P2P: el que transmite sube el video a cada espectador
function liveMembers(l, hostId) { return [hostId, ...l.viewers]; }
function liveOf(userId) {                // el live en el que participa este usuario (como host o espectador)
  if (lives.has(userId)) return [userId, lives.get(userId)];
  for (const [h, l] of lives) if (l.viewers.has(userId)) return [h, l];
  return null;
}
function liveCount(hostId) { const l = lives.get(hostId); if (l) for (const id of liveMembers(l, hostId)) push(id, 'live', { type: 'viewers', hostId, count: l.viewers.size }); }
function endLive(hostId) {
  const l = lives.get(hostId); if (!l) return;
  lives.delete(hostId);
  broadcast('live', { type: 'end', hostId });
}
function dropFromLives(userId) {
  if (lives.has(userId)) return endLive(userId);
  for (const [h, l] of lives) if (l.viewers.delete(userId)) { push(h, 'signal', { from: userId, kind: 'leave' }); liveCount(h); }
}
const liveList = () => [...lives].map(([hostId, l]) => ({ hostId, name: l.name, title: l.title, viewers: l.viewers.size, since: l.since }));
const iceServers = () => {
  const arr = [{ urls: 'stun:stun.l.google.com:19302' }];
  if (process.env.TURN_URL) arr.push({ urls: process.env.TURN_URL.split(','), username: process.env.TURN_USER || '', credential: process.env.TURN_PASS || '' });
  return arr;
};
const hits = new Map();         // límite simple de registros por IP
function tooMany(ip) {
  const t = now(), arr = (hits.get(ip) || []).filter(x => t - x < 10 * 60000);
  arr.push(t); hits.set(ip, arr);
  return arr.length > 15;
}

const MIME = { '.html':'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8', '.json':'application/json; charset=utf-8', '.webmanifest':'application/manifest+json', '.svg':'image/svg+xml', '.png':'image/png', '.jpg':'image/jpeg', '.jpeg':'image/jpeg', '.ico':'image/x-icon', '.webp':'image/webp', '.txt':'text/plain; charset=utf-8', '.css':'text/css; charset=utf-8' };

/* ---------- archivos estáticos con caché en memoria ---------- */
const assets = new Map();
const TEXTY = new Set(['.html', '.js', '.json', '.webmanifest', '.svg', '.txt', '.css']);
function getAsset(file) {
  let st; try { st = fs.statSync(file); } catch { return null; }
  if (!st.isFile()) return null;
  const ext = path.extname(file).toLowerCase();
  const isSw = path.basename(file) === 'sw.js';
  let a = assets.get(file);
  if (!isSw && a && a.mtimeMs === st.mtimeMs) return a;
  let buf = fs.readFileSync(file);
  if (isSw) {                                         // la versión del SW = huella de la app → cada despliegue renueva la caché del teléfono
    const idx = getAsset(path.join(ROOT, 'index.html'));
    buf = Buffer.from(buf.toString('utf8').replace(/__BUILD__/g, idx ? idx.etag.replace(/"/g, '') : 'dev'));
  }
  a = { mtimeMs: st.mtimeMs, buf, type: MIME[ext] || 'application/octet-stream',
    etag: '"' + crypto.createHash('sha1').update(buf).digest('hex').slice(0, 20) + '"',
    cache: (ext === '.png' || ext === '.ico' || ext === '.jpg' || ext === '.webp') ? 'public, max-age=604800' : 'no-cache' };
  if (TEXTY.has(ext) && buf.length > 1024) {
    a.gz = zlib.gzipSync(buf, { level: 9 });
    a.br = zlib.brotliCompressSync(buf, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 6 } });
  }
  assets.set(file, a);
  return a;
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost');
  const p = url.pathname;
  res.setHeader('X-Content-Type-Options', 'nosniff');

  /* ---------- API ---------- */
  if (p === '/api/health') return sendJson(res, 200, Object.assign({ ok: true, db: 'sqlite' }, q.counts.get()));

  if (p === '/api/register' && req.method === 'POST') {
    const ip = String(req.headers['x-forwarded-for'] || req.socket.remoteAddress || '').split(',')[0].trim();
    if (tooMany(ip)) return sendJson(res, 429, { error: 'Demasiados intentos. Espera unos minutos.' });
    let b; try { b = await readBody(req); } catch { return sendJson(res, 413, { error: 'Cuerpo inválido' }); }
    const name = String(b.name || '').trim().replace(/\s+/g, ' ').slice(0, 60);
    const country = String(b.country || '').trim().slice(0, 48);
    const dial = String(b.dial || '').trim().slice(0, 10);
    const phone = String(b.phone || '').replace(/[^\d]/g, '').slice(0, 15);
    if (name.length < 3) return sendJson(res, 400, { error: 'Escribe tu nombre completo.' });
    if (!country || !dial) return sendJson(res, 400, { error: 'Elige tu país.' });
    if (phone.length < 6) return sendJson(res, 400, { error: 'Escribe un número válido.' });
    let user = q.userByPhone.get(dial, phone);
    if (user) q.updUser.run(name, country, now(), user.id);
    else { user = { id: newId(), name, country, dial, phone, created: now(), last_seen: now() }; q.insUser.run(user.id, name, country, dial, phone, user.created, user.last_seen); }
    const token = crypto.randomBytes(24).toString('hex');
    q.insSess.run(hash(token), user.id, now());
    online.set(user.id, now());
    return sendJson(res, 200, { user: pubUser(q.userById.get(user.id)), token });
  }

  if (p.startsWith('/api/')) {
    const me = authUser(req, url);
    if (!me) return sendJson(res, 401, { error: 'Sesión no válida. Vuelve a registrarte.' });

    if (p === '/api/stream' && req.method === 'GET') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache, no-transform', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no' });
      res.write('retry: 3000\n\nevent: ready\ndata: {}\n\n');
      if (!streams.has(me.id)) streams.set(me.id, new Set());
      streams.get(me.id).add(res);
      q.seen.run(now(), me.id);
      const hb = setInterval(() => res.write(': ping\n\n'), 20000);
      req.on('close', () => { clearInterval(hb); const s = streams.get(me.id); if (s) { s.delete(res); if (!s.size) streams.delete(me.id); } q.seen.run(now(), me.id);
        if (!streams.has(me.id)) setTimeout(() => { if (!streams.has(me.id)) dropFromLives(me.id); }, 20000); });
      return;
    }

    if (p === '/api/ping' && req.method === 'POST') {
      online.set(me.id, now()); q.seen.run(now(), me.id);
      return sendJson(res, 200, { ok: true });
    }

    if (p === '/api/users' && req.method === 'GET') {
      return sendJson(res, 200, { users: q.allUsers.all(me.id).map(u => Object.assign(pubUser(u), { online: isOnline(u) })) });
    }

    if (p === '/api/messages' && req.method === 'POST') {
      let b; try { b = await readBody(req); } catch { return sendJson(res, 413, { error: 'Mensaje demasiado grande' }); }
      const to = String(b.to || '');
      const kind = ['text', 'audio', 'image'].includes(b.kind) ? b.kind : 'text';
      const payload = String(b.payload || '');
      if (!q.userById.get(to)) return sendJson(res, 400, { error: 'Usuarios no válidos' });
      if (kind === 'text' && !payload.trim()) return sendJson(res, 400, { error: 'Mensaje vacío' });
      if (kind === 'text' && payload.length > 8000) return sendJson(res, 413, { error: 'Mensaje demasiado largo' });
      if (payload.length > 5.5 * 1024 * 1024) return sendJson(res, 413, { error: 'Archivo demasiado grande' });
      const dur = b.dur ? Math.min(3600, +b.dur || 0) : null;
      const m = { id: newId(), from_id: me.id, to_id: to, kind, payload, dur, ts: now() };
      q.insMsg.run(m.id, m.from_id, m.to_id, m.kind, m.payload, m.dur, m.ts);
      q.prune.run();
      const out = msgOut(m);
      push(to, 'message', out);                    // entrega instantánea al destinatario
      return sendJson(res, 200, { message: out });
    }

    if (p === '/api/messages' && req.method === 'GET') {
      const since = Math.max(0, +(url.searchParams.get('since') || 0));
      return sendJson(res, 200, { messages: q.msgsSince.all(me.id, me.id, since).map(msgOut), now: now() });
    }

    /* ----- live ----- */
    if (p === '/api/live' && req.method === 'GET') return sendJson(res, 200, { lives: liveList(), ice: iceServers() });
    if (p === '/api/live/start' && req.method === 'POST') {
      let b; try { b = await readBody(req); } catch { b = {}; }
      dropFromLives(me.id);
      lives.set(me.id, { title: String(b.title || '').trim().slice(0, 60), name: me.name, since: now(), viewers: new Set() });
      for (const id of streams.keys()) if (id !== me.id) push(id, 'live', { type: 'start', hostId: me.id, name: me.name, title: lives.get(me.id).title });
      return sendJson(res, 200, { ok: true, ice: iceServers() });
    }
    if (p === '/api/live/stop' && req.method === 'POST') { endLive(me.id); return sendJson(res, 200, { ok: true }); }
    if (p === '/api/live/signal' && req.method === 'POST') {
      let b; try { b = await readBody(req); } catch { return sendJson(res, 400, { error: 'Cuerpo inválido' }); }
      const to = String(b.to || ''), kind = ['offer', 'answer', 'ice'].includes(b.kind) ? b.kind : null;
      const mine = liveOf(me.id);
      if (!kind || !mine || !liveMembers(mine[1], mine[0]).includes(to) || to === me.id) return sendJson(res, 400, { error: 'Señal no válida' });
      if (me.id !== mine[0] && to !== mine[0]) return sendJson(res, 400, { error: 'Señal no válida' });   // espectador solo habla con el host
      push(to, 'signal', { from: me.id, kind, data: b.data });
      return sendJson(res, 200, { ok: true });
    }
    let lm;
    if ((lm = /^\/api\/live\/([0-9a-f]+)\/(join|leave|chat|heart)$/.exec(p)) && req.method === 'POST') {
      const hostId = lm[1], act = lm[2], l = lives.get(hostId);
      if (!l && act === 'leave') return sendJson(res, 200, { ok: true });      // salir de un live ya terminado no es un error
      if (!l) return sendJson(res, 404, { error: 'Esta transmisión ya terminó.' });
      if (act === 'join') {
        if (hostId === me.id) return sendJson(res, 400, { error: 'Ese live es tuyo.' });
        if (!l.viewers.has(me.id) && l.viewers.size >= MAX_VIEWERS) return sendJson(res, 409, { error: 'El live está lleno (máx. ' + MAX_VIEWERS + ').' });
        dropFromLives(me.id);
        l.viewers.add(me.id);
        push(hostId, 'signal', { from: me.id, kind: 'join', name: me.name });
        liveCount(hostId);
        return sendJson(res, 200, { ok: true, title: l.title, name: l.name, viewers: l.viewers.size, ice: iceServers() });
      }
      if (act === 'leave') { if (l.viewers.delete(me.id)) { push(hostId, 'signal', { from: me.id, kind: 'leave' }); liveCount(hostId); } return sendJson(res, 200, { ok: true }); }
      if (hostId !== me.id && !l.viewers.has(me.id)) return sendJson(res, 403, { error: 'No estás en este live.' });
      if (act === 'chat') {
        let b; try { b = await readBody(req); } catch { return sendJson(res, 400, { error: 'Cuerpo inválido' }); }
        const text = String(b.text || '').trim().slice(0, 120); if (!text) return sendJson(res, 400, { error: 'Comentario vacío' });
        for (const id of liveMembers(l, hostId)) push(id, 'live-chat', { hostId, userId: me.id, name: me.name, text, ts: now() });
        return sendJson(res, 200, { ok: true });
      }
      if (act === 'heart') {
        let b; try { b = await readBody(req); } catch { b = {}; }
        const emoji = ['❤️', '💖', '🧡', '💕', '🌹'].includes(b.emoji) ? b.emoji : '❤️';
        for (const id of liveMembers(l, hostId)) if (id !== me.id) push(id, 'live-heart', { hostId, emoji });
        return sendJson(res, 200, { ok: true });
      }
    }

    /* ----- feed (Vibra) ----- */
    if (p === '/api/posts' && req.method === 'GET') {
      return sendJson(res, 200, { posts: q.feed.all(me.id, me.id).map(postOut) });
    }
    if (p === '/api/posts' && req.method === 'POST') {
      let b; try { b = await readBody(req); } catch { return sendJson(res, 413, { error: 'Publicación demasiado grande' }); }
      const caption = String(b.caption || '').trim().slice(0, 150);
      const text = String(b.text || '').trim().slice(0, 300);
      let image = null;
      if (b.img) { image = saveImage(b.img); if (!image) return sendJson(res, 400, { error: 'Imagen no válida o demasiado grande (máx. 4 MB)' }); }
      if (!caption && !text && !image) return sendJson(res, 400, { error: 'Escribe algo o sube una foto.' });
      let product = null;
      if (b.product && b.product.name && +b.product.price > 0)
        product = JSON.stringify({ name: String(b.product.name).slice(0, 70), price: Math.min(+b.product.price, 1e9), emoji: String(b.product.emoji || '🛍️').slice(0, 8) });
      const r = q.insPost.run(me.id, caption, text, image, String(b.emoji || '🎬').slice(0, 8), String(b.grad || '').slice(0, 200), product, now());
      broadcast('feed', { type: 'post', id: Number(r.lastInsertRowid), by: me.id });
      return sendJson(res, 200, { id: Number(r.lastInsertRowid) });
    }
    let mm;
    if ((mm = /^\/api\/posts\/(\d+)\/like$/.exec(p)) && req.method === 'POST') {
      const id = +mm[1]; if (!q.postById.get(id)) return sendJson(res, 404, { error: 'No existe esa publicación' });
      let b; try { b = await readBody(req); } catch { b = {}; }
      if (b.on === false) q.delLike.run(id, me.id); else q.addLike.run(id, me.id);
      const likes = q.likeCount.get(id).n;
      broadcast('feed', { type: 'like', id, likes, by: me.id });
      return sendJson(res, 200, { liked: b.on !== false, likes });
    }
    if ((mm = /^\/api\/posts\/(\d+)\/comments$/.exec(p))) {
      const id = +mm[1]; if (!q.postById.get(id)) return sendJson(res, 404, { error: 'No existe esa publicación' });
      if (req.method === 'GET') return sendJson(res, 200, { comments: q.comList.all(id).map(c => ({ id: c.id, text: c.text, ts: c.ts, userId: c.user_id, name: c.name })) });
      if (req.method === 'POST') {
        let b; try { b = await readBody(req); } catch { return sendJson(res, 400, { error: 'Cuerpo inválido' }); }
        const text = String(b.text || '').trim().slice(0, 500);
        if (!text) return sendJson(res, 400, { error: 'Comentario vacío' });
        const ts = now(), r = q.insCom.run(id, me.id, text, ts);
        const comments = q.comCount.get(id).n;
        broadcast('feed', { type: 'comment', id, comments, by: me.id });
        return sendJson(res, 200, { comment: { id: Number(r.lastInsertRowid), text, ts, userId: me.id, name: me.name }, comments });
      }
    }
    if ((mm = /^\/api\/follow\/([0-9a-f]+)$/.exec(p)) && req.method === 'POST') {
      const target = mm[1]; if (target === me.id || !q.userById.get(target)) return sendJson(res, 400, { error: 'Usuario no válido' });
      let b; try { b = await readBody(req); } catch { b = {}; }
      if (b.on === false) q.delFollow.run(me.id, target); else q.addFollow.run(me.id, target);
      return sendJson(res, 200, { following: b.on !== false });
    }

    return sendJson(res, 404, { error: 'No existe' });
  }

  /* ---------- archivos subidos (nombres aleatorios, no adivinables) ---------- */
  if (p.startsWith('/media/')) {
    const name = path.basename(p);
    if (!/^[0-9a-f]{24}\.(jpg|png|webp)$/.test(name)) { res.writeHead(404); return res.end('No encontrado'); }
    return fs.readFile(path.join(MEDIA_DIR, name), (err, buf) => {
      if (err) { res.writeHead(404); return res.end('No encontrado'); }
      res.writeHead(200, { 'Content-Type': MIME['.' + name.split('.')[1]] || 'application/octet-stream', 'Cache-Control': 'public, max-age=31536000, immutable' });
      res.end(buf);
    });
  }

  /* ---------- estáticos (la app): comprimidos, con ETag y caché ---------- */
  let fpath;
  try { fpath = decodeURIComponent(p); } catch { res.writeHead(400); return res.end('no'); }
  if (fpath === '/') fpath = '/index.html';
  const file = path.normalize(path.join(ROOT, fpath));
  if (!file.startsWith(ROOT)) { res.writeHead(403); return res.end('no'); }
  const asset = getAsset(file);
  if (!asset) { res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' }); return res.end('No encontrado'); }
  const heads = { 'Content-Type': asset.type, 'ETag': asset.etag, 'Vary': 'Accept-Encoding', 'Cache-Control': asset.cache };
  if (req.headers['if-none-match'] === asset.etag) { res.writeHead(304, heads); return res.end(); }
  const ae = String(req.headers['accept-encoding'] || '');
  let body = asset.buf;
  if (asset.br && /\bbr\b/.test(ae)) { body = asset.br; heads['Content-Encoding'] = 'br'; }
  else if (asset.gz && /\bgzip\b/.test(ae)) { body = asset.gz; heads['Content-Encoding'] = 'gzip'; }
  heads['Content-Length'] = body.length;
  res.writeHead(200, heads);
  res.end(req.method === 'HEAD' ? undefined : body);
});

server.listen(PORT, '0.0.0.0', () => console.log('Caribe v3 en línea · http://0.0.0.0:' + PORT + ' · datos en ' + DATA_DIR));
process.on('SIGTERM', () => { try { db.close(); } catch (_) {} process.exit(0); });
