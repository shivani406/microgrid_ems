/* Operator console: everything shown comes from /api/site, /api/history and /ws/live. No fabricated data. */
const COL = {local:'#FFD60A', imp:'#A855F7', exp:'#22D3EE', dis:'#FB923C', chg:'#3B82F6', idle:'#64748B'};
const STC = {OK:'#22C55E', DEGRADED:'#F59E0B', FAULT:'#EF4444', OFFLINE:'#64748B'};
const ICON = {OK:'✓', DEGRADED:'!', FAULT:'✕', OFFLINE:'–'};
const $ = id => document.getElementById(id);
const fmt = (v, d = 1) => Number(v).toLocaleString('en-IN', {minimumFractionDigits:d, maximumFractionDigits:d});
const post = (p, q) => fetch(p + (q ? '?' + new URLSearchParams(q) : ''), {method:'POST'}).then(r => r.json());
let site, S = null, hist = [], lastMsg = 0, ws, playing = false;

$('legend').innerHTML = '<h3>Colour code</h3>' + [['Local flow (PV/WT)',COL.local],['Import from main grid',COL.imp],['Export to main grid',COL.exp],
  ['Battery discharging',COL.dis],['Battery charging',COL.chg],['Idle line',COL.idle],['OK',STC.OK],['Fault / tripped',STC.FAULT],['Degraded',STC.DEGRADED],['Offline',STC.OFFLINE]]
  .map(([t, c]) => `<div><i style="background:${c}"></i>${t}</div>`).join('');

/* ---------------- 3D scene (built from the registry) ---------------- */
const renderer = new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); $('view').appendChild(renderer.domElement);
const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(45, 1, 1, 1500);
const controls = new THREE.OrbitControls(camera, renderer.domElement);
Object.assign(controls, {enableDamping:true, dampingFactor:.08, minDistance:20, maxDistance:320, maxPolarAngle:1.45, screenSpacePanning:false});
const sunL = new THREE.DirectionalLight(0xffffff, 1), hemi = new THREE.HemisphereLight(0xbfd9ff, 0x3a4a3a, .5);
scene.add(sunL, hemi);
const PRESETS = {overview:[[0,0,20],[100,80,150]], pv:[[-45,0,52],[-15,30,110]], batt:[[42,0,50],[75,25,95]], grid:[[80,0,18],[125,30,60]], res:[[2,0,-4],[10,28,45]]};
let tween = null;
function flyTo(t, p, ms = 900) { tween = {t0:performance.now(), ms, ft:controls.target.clone(), fp:camera.position.clone(), tt:new THREE.Vector3(...t), tp:new THREE.Vector3(...p)}; }
function setView(k) { const [t, p] = PRESETS[k]; flyTo(t, p); }

const mat = (c, o = {}) => new THREE.MeshStandardMaterial(Object.assign({color:c, roughness:.8}, o));
const box = (w, h, d, c, x = 0, y = 0, z = 0) => { const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(c)); m.position.set(x, y + h / 2, z); return m; };
const cyl = (r1, r2, h, c, x = 0, y = 0, z = 0) => { const m = new THREE.Mesh(new THREE.CylinderGeometry(r1, r2, h, 12), mat(c)); m.position.set(x, y + h / 2, z); return m; };
const MODELS = {
  pv_field(a, g) { const n = a.twin.panels || 100, cols = 16, rows = Math.ceil(n / cols), d = new THREE.Object3D();
    const im = new THREE.InstancedMesh(new THREE.BoxGeometry(2.4, .1, 1.4), mat(0x1e3a8a, {metalness:.4, roughness:.3}), n);
    for (let i = 0; i < n; i++) { d.position.set((i % cols - cols / 2) * 2.8, 1.2, (Math.floor(i / cols) - rows / 2) * 2.4); d.rotation.x = -.35; d.updateMatrix(); im.setMatrixAt(i, d.matrix); }
    g.add(box(46, .2, rows * 2.4 + 2, 0x6b7280), im); g.userData.h = 5; },
  wind_turbine(a, g) { g.add(cyl(.5, .9, 24, 0xf1f5f9), box(1.4, 1.2, 3, 0xe2e8f0, 0, 23.4, .6));
    const r = new THREE.Group(); r.position.set(0, 24, 2.2);
    for (let i = 0; i < 3; i++) { const b = new THREE.Group(); const m = box(.7, 11, .15, 0xf8fafc, 0, 0, 0); b.add(m); b.rotation.z = i * 2.094; r.add(b); }
    g.add(r); g.userData.rotor = r; g.userData.h = 30; },
  bess_container(a, g) { for (let i = 0; i < 3; i++) g.add(box(12, 3, 2.6, 0xe5e7eb, 0, 0, (i - 1) * 3.4), box(12.1, .5, 2.7, 0x16a34a, 0, 1.2, (i - 1) * 3.4));
    const f = box(.8, 6, .8, 0x22d3ee, 8, 0, 0); f.geometry.translate(0, 0, 0); g.add(f); g.userData.fill = f; g.userData.h = 8; },
  substation(a, g) { g.add(box(6, 4, 6, 0x9ca3af), cyl(.25, .25, 14, 0x4b5563, -7, 0, -3), cyl(.25, .25, 14, 0x4b5563, -7, 0, 3), box(.4, .4, 8, 0x4b5563, -7, 13, 0), box(.4, .4, 6, 0x4b5563, -7, 10, 0)); g.userData.h = 15; },
  house(a, g) { g.add(box(7, 4, 7, 0xf1f5f9)); const r = new THREE.Mesh(new THREE.ConeGeometry(5.6, 2.6, 4), mat(0xb45309)); r.position.y = 5.3; r.rotation.y = Math.PI / 4; g.add(r); g.userData.h = 9; },
  building(a, g) { g.add(box(12, 8, 10, 0xdbe4ee), box(12.2, .5, 10.2, 0x94a3b8, 0, 8, 0)); g.userData.h = 11; },
  bus(a, g) { g.add(box(3, 1.6, 3, 0x1f2937), box(3.2, .3, 3.2, 0xffd60a, 0, 1.6, 0)); g.userData.h = 4; },
};
const RING = {pv_field:[26,27.2], wind_turbine:[5,6], bess_container:[10,11], substation:[7,8], house:[6,7], building:[9,10], bus:[3,4]};
const groups = {}, rings = {}, lbls = {}, edgeObjs = {}, hitRoots = [];
const posOf = id => groups[id].position;

function buildScene() {
  const flat = (w, d, x, y, z, c) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(w, d), mat(c)); m.rotation.x = -Math.PI / 2; m.position.set(x, y, z); scene.add(m); };
  flat(420, 320, 0, -.05, 20, 0x4a7c4a);
  for (const [w, d, x, z] of [[420, 6, 0, 3], [6, 130, 0, 20], [420, 6, 0, 36]]) flat(w, d, x, 0, z, 0x374151);
  const items = site.buses.map(b => ({id:b.id, twin:b.twin, type:'bus'})).concat(site.assets);
  items.forEach(a => {
    const g = new THREE.Group(); g.position.set(...a.twin.pos); MODELS[a.twin.model](a, g);
    g.traverse(o => { o.userData.aid = a.id; }); scene.add(g); groups[a.id] = g; hitRoots.push(g);
    const [r1, r2] = RING[a.twin.model] || [6, 7];
    const ring = new THREE.Mesh(new THREE.RingGeometry(r1, r2, 40), new THREE.MeshBasicMaterial({color:STC.OK, side:THREE.DoubleSide, transparent:true, opacity:.9}));
    ring.rotation.x = -Math.PI / 2; ring.position.set(...a.twin.pos); ring.position.y = .15; scene.add(ring); rings[a.id] = ring;
    if (a.type !== 'bus') { const d = document.createElement('div'); d.className = 'lbl'; d.innerHTML = `<i>✓</i><b>${a.id.replace(site.site.id + '-', '')}</b><span>0 kW</span>`; $('labels').appendChild(d); lbls[a.id] = d; }
  });
  site.topology.forEach(([a, b]) => {
    const pa = posOf(a).clone().setY(3), pb = posOf(b).clone().setY(3), mid = pa.clone().add(pb).multiplyScalar(.5); mid.y += 7;
    const curve = new THREE.CatmullRomCurve3([pa, mid, pb]);
    scene.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 24, .22, 6), mat(0x475569)));
    const N = 24, geo = new THREE.BufferGeometry(), pos = new Float32Array(N * 3), col = new Float32Array(N * 3);
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3)); geo.setAttribute('color', new THREE.BufferAttribute(col, 3)); geo.setDrawRange(0, 0);
    const pts = new THREE.Points(geo, new THREE.PointsMaterial({size:6, sizeAttenuation:false, vertexColors:true})); pts.frustumCulled = false; scene.add(pts);
    edgeObjs[`${a}>${b}`] = {curve, pts, u:Float32Array.from({length:N}, (_, i) => i / N), N, n:0, kw:0, kind:'idle', dir:1, shares:{}};
  });
  setView('overview'); camera.position.set(...PRESETS.overview[1]); controls.target.set(...PRESETS.overview[0]);
}
function pickColor(E) {
  const k = E.kind; if (k === 'pv' || k === 'wt') return COL.local; if (k === 'dis') return COL.dis; if (k === 'imp') return COL.imp; if (k === 'exp') return COL.exp; if (k === 'chg') return COL.chg;
  let r = Math.random(), s = E.shares || {}; const mix = [['pv', COL.local], ['wt', COL.local], ['batt', COL.dis], ['grid', COL.imp]];
  for (const [n, c] of mix) { if ((r -= s[n] || 0) < 0) return c; } return COL.local;
}
const tmpV = new THREE.Vector3(), tmpC = new THREE.Color();
function animate(now) {
  const dt = Math.min(.1, (now - (animate.prev || now)) / 1000); animate.prev = now;
  if (tween) { const k = Math.min(1, (now - tween.t0) / tween.ms), e = k * k * (3 - 2 * k); controls.target.lerpVectors(tween.ft, tween.tt, e); camera.position.lerpVectors(tween.fp, tween.tp, e); if (k >= 1) tween = null; }
  for (const E of Object.values(edgeObjs)) {
    if (!E.n) continue; const sp = Math.min(.7, .06 + E.kw * .006), P = E.pts.geometry.attributes.position, C = E.pts.geometry.attributes.color;
    for (let i = 0; i < E.n; i++) {
      E.u[i] += E.dir * sp * dt; let w = false; if (E.u[i] > 1) { E.u[i] -= 1; w = true } else if (E.u[i] < 0) { E.u[i] += 1; w = true }
      E.curve.getPoint(E.u[i], tmpV); P.setXYZ(i, tmpV.x, tmpV.y, tmpV.z);
      if (w || E.fresh) { tmpC.set(pickColor(E)); C.setXYZ(i, tmpC.r, tmpC.g, tmpC.b); }
    }
    E.fresh = false; P.needsUpdate = C.needsUpdate = true;
  }
  const wtg = groups[site.assets.find(a => a.type === 'wind_turbine').id]; if (S && wtg.userData.rotor) wtg.userData.rotor.rotation.z -= dt * (S.assets[Object.keys(S.assets).find(k => k.includes('-WT-'))].kw / 30) * 6;
  controls.update(); const W = innerWidth, H = innerHeight;
  for (const id in lbls) { tmpV.copy(groups[id].position); tmpV.y += groups[id].userData.h || 8; tmpV.project(camera);
    lbls[id].style.display = tmpV.z < 1 ? '' : 'none'; lbls[id].style.transform = `translate(${(tmpV.x * .5 + .5) * W}px,${(-tmpV.y * .5 + .5) * H}px) translate(-50%,-110%)`; }
  renderer.render(scene, camera); requestAnimationFrame(animate);
}
function resize() { renderer.setSize(innerWidth, innerHeight); camera.aspect = innerWidth / innerHeight; camera.updateProjectionMatrix(); drawCharts(); }
addEventListener('resize', resize);

/* click = inspect, double-click = focus */
const ray = new THREE.Raycaster(), ndc = new THREE.Vector2(); let down = null;
function hit(ev) { ndc.set(ev.clientX / innerWidth * 2 - 1, -(ev.clientY / innerHeight) * 2 + 1); ray.setFromCamera(ndc, camera); const h = ray.intersectObjects(hitRoots, true)[0]; return h && h.object.userData.aid; }
renderer.domElement.addEventListener('pointerdown', e => down = [e.clientX, e.clientY]);
renderer.domElement.addEventListener('pointerup', e => { if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4) return; const id = hit(e); id ? inspect(id) : $('inspector').hidden = true; });
renderer.domElement.addEventListener('dblclick', e => { const id = hit(e); if (id) { const p = posOf(id); flyTo([p.x, 0, p.z], [p.x + 25, 22, p.z + 38]); } });
function inspect(id) {
  const a = site.assets.find(x => x.id === id); if (!a) return; const live = S && S.assets[id] || {}, skip = ['twin', 'bus', 'id', 'type', 'tariff'];
  $('inspector').innerHTML = `<h3>${id}</h3><b>${a.type}</b> · <span style="color:${STC[live.status || 'OFFLINE']}">${live.status || 'n/a'}</span><br>Now: <b class="num">${fmt(live.kw || 0)} kW</b>${live.shed ? ' · SHED' : ''}<hr style="border-color:#22d3ee33">` +
    Object.entries(a).filter(([k]) => !skip.includes(k)).map(([k, v]) => `${k}: <span class="num">${v}</span>`).join('<br>'); $('inspector').hidden = false;
}

/* ---------------- state -> HUD / scene ---------------- */
function applyState() {
  const s = S, B = site.assets.find(a => a.type === 'battery');
  $('date').textContent = s.t; $('t-pv').textContent = fmt(s.pv); $('t-wt').textContent = fmt(s.wt); $('t-load').textContent = fmt(s.load);
  $('t-imp').textContent = fmt(s.imp); $('t-exp').textContent = fmt(s.exp); $('t-step').textContent = s.step;
  $('k-coe').textContent = fmt(s.kpi.coe, 3); $('k-ref').textContent = fmt(s.kpi.ref, 1) + '%'; $('k-buy').textContent = fmt(s.kpi.buy); $('k-sell').textContent = fmt(s.kpi.sell); $('k-curt').textContent = fmt(s.kpi.curt);
  $('b-kwh').textContent = fmt(s.batt_kwh, 2) + ' kWh'; $('b-soc').textContent = fmt(s.soc, 1) + '%'; $('soc-fill').style.width = s.soc + '%';
  $('soc-min').style.left = B.soc_min_pct + '%'; $('soc-max').style.left = B.soc_max_pct + '%';
  $('b-mode').textContent = `${s.mode_id}-${s.mode_text}`; $('b-soh').textContent = fmt(s.soh, 2) + '%'; $('b-temp').textContent = fmt(s.temp_b, 1) + '°C'; $('b-price').textContent = '₹' + fmt(s.price) + '/kWh';
  $('why').textContent = s.why;
  $('alarms').innerHTML = s.alarms.length ? s.alarms.map(a => `<span class="al ${a.level}">${a.level === 'critical' ? '✕' : '!'} ${a.text}</span>`).join('') : '<span class="al" style="color:#22C55E">✓ No active alarms</span>';
  const crit = s.alarms.some(a => a.level === 'critical');
  setPill(crit ? 'fault' : (s.alarms.length ? 'warn' : 'ok'), !s.grid_up ? 'ISLANDED' : crit ? 'FAULT ACTIVE' : s.alarms.length ? 'WARNING' : 'NORMAL OPERATION');
  for (const id in s.assets) { const a = s.assets[id], L = lbls[id]; if (!L) continue; const c = a.shed ? '#EF4444' : STC[a.status];
    L.style.setProperty('--c', c); L.querySelector('i').textContent = a.shed ? '⏻' : ICON[a.status]; L.querySelector('span').textContent = fmt(a.kw) + ' kW' + (a.shed ? ' SHED' : ''); rings[id].material.color.set(c);
    groups[id].traverse(o => { if (o.material) { o.material.transparent = true; o.material.opacity = a.shed ? .35 : 1; } }); }
  const bg = groups[B.id].userData.fill; if (bg) { bg.scale.y = Math.max(.02, s.soc / 100); bg.position.y = 3 * bg.scale.y; }
  s.edges.forEach(e => { const E = edgeObjs[e.id]; if (!E) return; Object.assign(E, {kw:e.kw, kind:e.kind, dir:e.dir, shares:e.shares}); E.n = e.kw > .3 ? Math.min(E.N, Math.ceil(2 + e.kw / 3)) : 0; E.fresh = true; E.pts.geometry.setDrawRange(0, E.n); });
  const el = s.sun[0], az = s.sun[1], up = Math.max(0, Math.sin(el));
  sunL.position.set(Math.cos(el) * Math.sin(az) * 200, Math.max(10, Math.sin(el) * 200), -Math.cos(el) * Math.cos(az) * 200); sunL.intensity = .1 + .95 * up; hemi.intensity = .25 + .35 * up;
  const sky = new THREE.Color(0x050b18).lerp(new THREE.Color(0x7fb5e6), Math.min(1, up * 2.2)); scene.background = sky; scene.fog = new THREE.Fog(sky, 300, 700);
  $('bPlay').classList.toggle('on', playing); $('bPause').classList.toggle('on', !playing);
}
function setPill(cls, txt) { const p = $('status'); p.className = 'pill ' + cls; p.textContent = txt; }

/* ---------------- charts (48 h, canvas) ---------------- */
function chart(id, series, {ymax, fixed} = {}) {
  const c = $(id), x = c.getContext('2d'), dpr = devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight; if (!w) return;
  if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
  x.setTransform(dpr, 0, 0, dpr, 0, 0); x.clearRect(0, 0, w, h); if (!hist.length) return;
  const tn = hist[hist.length - 1].t, t0 = tn - 48 * 3600e3, L = 34, R = 6, T = 4, Bm = 14;
  let m = ymax || 1; if (!fixed) for (const p of hist) for (const s of series) m = Math.max(m, p[s.k] * 1.08);
  const X = t => L + (t - t0) / (tn - t0) * (w - L - R), Y = v => T + (1 - v / m) * (h - T - Bm);
  x.font = '9px IBM Plex Mono, monospace'; x.lineWidth = 1;
  for (let i = 0; i <= 4; i++) { const v = m * i / 4, y = Y(v); x.strokeStyle = 'rgba(140,163,191,.18)'; x.beginPath(); x.moveTo(L, y); x.lineTo(w - R, y); x.stroke(); x.fillStyle = '#8CA3BF'; x.textAlign = 'right'; x.fillText(Math.round(v), L - 4, y + 3); }
  x.textAlign = 'center'; x.fillStyle = '#8CA3BF'; ['-48h', '-24h', 'now'].forEach((t, i) => x.fillText(t, [L + 10, (L + w - R) / 2, w - R - 8][i], h - 3));
  for (const s of series) { x.strokeStyle = s.c; x.lineWidth = 1.4; x.beginPath(); let f = true;
    for (const p of hist) { if (p.t < t0) continue; const px = X(p.t), py = Y(p[s.k]); f ? x.moveTo(px, py) : x.lineTo(px, py); f = false; } x.stroke(); }
  return {X, Y, x, L, w, R};
}
function drawCharts() {
  chart('c1', [{k:'pv', c:'#FFD60A'}, {k:'wt', c:'#2DD4BF'}, {k:'load', c:'#F97316'}]);
  const g = chart('c2', [{k:'soc', c:'#3B82F6'}], {ymax:100, fixed:true}), B = site && site.assets.find(a => a.type === 'battery');
  if (g && B) { g.x.setLineDash([3, 3]); g.x.strokeStyle = '#ffffff66'; for (const v of [B.soc_min_pct, B.soc_max_pct]) { g.x.beginPath(); g.x.moveTo(g.L, g.Y(v)); g.x.lineTo(g.w - g.R, g.Y(v)); g.x.stroke(); } g.x.setLineDash([]); }
  chart('c3', [{k:'imp', c:'#A855F7'}, {k:'exp', c:'#22D3EE'}]);
}
$('lg1').innerHTML = '<b style="color:#FFD60A">PV</b><b style="color:#2DD4BF">WT</b><b style="color:#F97316">Load</b>';
$('lg3').innerHTML = '<b style="color:#A855F7">Buy</b><b style="color:#22D3EE">Sell</b>';

/* ---------------- live link (snapshot on connect, STALE detection, auto-reconnect) ---------------- */
let fails = 0, poll = null;
function onMsg(m) {
  lastMsg = Date.now(); S = m.state; playing = m.playing; document.body.classList.remove('stale');
  m.points.forEach(p => hist.push(p)); const cut = (hist.length ? hist[hist.length - 1].t : 0) - 48 * 3600e3; while (hist.length && hist[0].t < cut) hist.shift();
  document.querySelectorAll('#simbar [data-s]').forEach(b => b.classList.toggle('on', +b.dataset.s === m.speed)); $('scn').value = m.scenario; applyState(); drawCharts();
}
async function pollOnce() {   // fallback when the WebSocket cannot connect (e.g. websockets library missing)
  try { const m = await (await fetch('/api/state')).json(), s = m.state;
    if (!S || s.step !== S.step) m.points = [{t:s.ts, pv:s.pv, wt:s.wt, load:s.load, imp:s.imp, exp:s.exp, soc:s.soc}]; onMsg(m); } catch (e) {}
}
function connect() {
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/live');
  ws.onopen = () => { fails = 0; clearInterval(poll); poll = null; };
  ws.onmessage = ev => onMsg(JSON.parse(ev.data));
  ws.onclose = () => { if (++fails >= 2 && !poll) { poll = setInterval(pollOnce, 1000); pollOnce(); } setTimeout(connect, 1500); };
}
setInterval(() => { if (lastMsg && Date.now() - lastMsg > 3000) { document.body.classList.add('stale'); setPill('stale', 'DATA STALE'); } }, 1000);

/* ---------------- controls ---------------- */
$('bPlay').onclick = () => post('/api/sim/play'); $('bPause').onclick = () => post('/api/sim/pause');
$('bReset').onclick = () => { hist = []; post('/api/sim/reset').then(boot2); }; $('bStep').onclick = () => post('/api/sim/step');
$('bLoad').onclick = () => { hist = []; post('/api/sim/load', {scenario:$('scn').value}).then(boot2); };
$('bFlt').onclick = () => { if (confirm(`Inject "${$('flt').value}" for 120 simulated minutes?`)) post('/api/sim/fault', {fault:$('flt').value, dur:120}); };
document.querySelectorAll('#simbar [data-s]').forEach(b => b.onclick = () => post('/api/sim/speed', {value:b.dataset.s}));
document.querySelectorAll('#presets [data-v]').forEach(b => b.onclick = () => setView(b.dataset.v));
addEventListener('keydown', e => { if (e.target.tagName === 'SELECT') return; if (e.code === 'Space') { e.preventDefault(); post('/api/sim/' + (playing ? 'pause' : 'play')); } else if ('123'.includes(e.key) && e.key) post('/api/sim/speed', {value:[1, 5, 20][+e.key - 1]}); });

async function boot2() { hist = await (await fetch('/api/history')).json(); drawCharts(); }
(async () => { try {
  if (!renderer.getContext()) { $('nogl').hidden = false; }
  site = await (await fetch('/api/site')).json();
  $('scn').innerHTML = site.scenarios.map(s => `<option>${s}</option>`).join(''); $('flt').innerHTML = site.faults.map(s => `<option>${s}</option>`).join('');
  buildScene(); resize(); await boot2(); connect(); requestAnimationFrame(animate);
} catch (e) { console.error(e); const b = $('banner'); b.style.background = '#EF4444'; b.style.color = '#fff'; b.textContent = 'UI ERROR: ' + e.message + ' - open DevTools (F12) > Console'; }
})();
