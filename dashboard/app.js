/*
 * RoadSense Lab — dashboard
 * Edge A = Android phone (sensor "imu"), Edge B = laptop (sensor "webcam"). Never swapped.
 * Plain browser JavaScript + MQTT.js (loaded from CDN in index.html). No build step.
 *
 * MQTT contract: SPEC.md v2 (LOCKED). Topic names and payload keys below must not be renamed.
 * This page never generates sensor values: every number shown comes from a received MQTT message.
 */
(() => {
  'use strict';

  // ---------------------------------------------------------------------------
  // Contract constants (SPEC.md v2)
  // ---------------------------------------------------------------------------
  const BROKER_URL = 'wss://broker.hivemq.com:8884/mqtt';
  const PROJECT_ID_RE = /^[a-z0-9-]{3,64}$/;
  // Unix epoch ms sanity floor (~Sep 2001). Smaller values are almost certainly
  // monotonic uptime or seconds, which SPEC.md v2 forbids for ts_ms.
  const EPOCH_MS_MIN = 1_000_000_000_000;

  // Units shown under each value. Android SensorManager reports acceleration in m/s²
  // and angular rate in rad/s. Peak jerk unit depends on how edge_phone differentiates
  // (Δa/Δt → m/s³). Confirm against edge_phone/ documentation and edit here if needed.
  const DEVICES = {
    A: {
      name: 'Phone',
      sensor: 'imu',
      statuses: ['NORMAL', 'BUMP_SUSPECTED', 'DEVICE_MOVEMENT', 'SENSOR_ERROR'],
      metrics: [
        { key: 'vibration_rms', label: 'Vibration RMS', unit: 'm/s²', color: '--c1', digits: 3 },
        { key: 'peak_jerk',     label: 'Peak jerk',     unit: 'm/s³', color: '--c2', digits: 3 },
        { key: 'rotation_rms',  label: 'Rotation RMS',  unit: 'rad/s', color: '--c3', digits: 3 },
      ],
      thresholds: [
        { key: 'vibration_rms_threshold', metric: 'vibration_rms' },
        { key: 'jerk_peak_threshold',     metric: 'peak_jerk' },
      ],
    },
    B: {
      name: 'Laptop webcam',
      sensor: 'webcam',
      statuses: ['NORMAL', 'MOTION_OBSERVED', 'SENSOR_ERROR'],
      metrics: [
        { key: 'motion_score', label: 'Motion score', unit: 'mean |Δ intensity|, ~0–255 (uncalibrated)', color: '--c1', digits: 2 },
        { key: 'motion_delta', label: 'Motion delta', unit: '|Δ motion_score| between samples', color: '--c2', digits: 2 },
      ],
      thresholds: [
        { key: 'motion_score_threshold', metric: 'motion_score' },
      ],
    },
  };
  const IDS = ['A', 'B'];

  // ---------------------------------------------------------------------------
  // Dashboard tuning (not part of the contract)
  // ---------------------------------------------------------------------------
  const CHART_WINDOW_MS = 60_000;
  const SERIES_KEEP_MS = 90_000;
  const ACK_TIMEOUT_MS = 10_000;
  const MAX_TIMELINE = 200;
  const MAX_LOG = 250;
  const REJECT_LOG_THROTTLE_MS = 5_000;
  const STORAGE_KEY = 'roadsense.dashboard.projectId';

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  const $ = (id) => document.getElementById(id);
  const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
  const safeStore = {
    get(k) { try { return window.localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { window.localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
  };
  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  const pad = (n, w = 2) => String(n).padStart(w, '0');
  function fmtClock(ms) {
    const d = new Date(ms);
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}`;
  }
  function fmtAge(ms) {
    if (ms < 1000) return 'just now';
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s ago`;
    if (ms < 3_600_000) return `${Math.floor(ms / 60_000)} min ago`;
    return `${Math.floor(ms / 3_600_000)} h ago`;
  }
  const fmtNum = (v, d) => (isNum(v) ? v.toFixed(d) : '—');
  const signed = (n) => (n >= 0 ? `+${n}` : String(n));
  function clip(s, n) { s = String(s); return s.length > n ? `${s.slice(0, n - 1)}…` : s; }
  const show = (v) => clip(JSON.stringify(v) ?? 'undefined', 40);
  function niceCeil(v) {
    if (!(v > 0)) return 1;
    const x = v * 1.1;
    const e = 10 ** Math.floor(Math.log10(x));
    const f = x / e;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
  }
  function fmtTick(v) {
    if (v === 0) return '0';
    const a = Math.abs(v);
    if (a >= 100) return v.toFixed(0);
    if (a >= 10) return v.toFixed(1);
    if (a >= 1) return v.toFixed(2);
    return v.toPrecision(2);
  }

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let client = null;
  let T = null; // topic map for the current PROJECT_ID
  let staleMs = 5000;
  let msgCount = 0;
  let rejCount = 0;
  let eventCount = 0;
  const rejectSeen = new Map();
  const hidden = { A: new Set(), B: new Set() };
  const pending = { A: null, B: null };
  const blank = () => ({
    last: null, rxAt: 0, series: [], thresholds: null,
    gaps: 0, lastSeq: null, count: 0, freshState: 'none',
  });
  const state = { A: blank(), B: blank() };

  function buildTopics(projectId) {
    const base = `roadsense/${projectId}`;
    return {
      base,
      telA: `${base}/edge/A/telemetry`,
      telB: `${base}/edge/B/telemetry`,
      events: `${base}/events`,
      control: `${base}/control`,
      ackA: `${base}/ack/A`,
      ackB: `${base}/ack/B`,
    };
  }
  const shortTopic = (t) => (T && t.startsWith(`${T.base}/`) ? t.slice(T.base.length + 1) : t);

  // ---------------------------------------------------------------------------
  // Connection
  // ---------------------------------------------------------------------------
  const CONN_TEXT = {
    disconnected: 'Disconnected',
    connecting: 'Connecting…',
    connected: 'Connected',
    reconnecting: 'Reconnecting…',
    error: 'Error',
  };
  function setConn(s, text) {
    $('connPill').dataset.state = s;
    $('connText').textContent = text || CONN_TEXT[s];
    $('connectBtn').disabled = s === 'connecting';
    $('connectBtn').textContent = client ? 'Reconnect' : 'Connect';
    $('disconnectBtn').disabled = !client;
    const live = s === 'connected';
    document.querySelectorAll('form.control button[type="submit"]').forEach((b) => { b.disabled = !live; });
  }
  function showConnError(msg) {
    const p = $('connError');
    p.textContent = msg || '';
    p.hidden = !msg;
  }

  function connect() {
    const pid = $('projectId').value.trim();
    showConnError('');
    if (!PROJECT_ID_RE.test(pid)) {
      showConnError('PROJECT_ID must be 3–64 characters: lowercase letters, digits and hyphen (e.g. roadsense-abc123).');
      return;
    }
    if (!window.mqtt || typeof window.mqtt.connect !== 'function') {
      showConnError('MQTT.js did not load. Check the internet connection — the library is loaded from a CDN.');
      return;
    }
    readStale();
    teardown();
    resetData();
    T = buildTopics(pid);
    $('baseTopic').textContent = T.base;
    safeStore.set(STORAGE_KEY, pid);

    const clientId = `rs-dash-${Math.random().toString(16).slice(2, 10)}`;
    log('sys', `Connecting to ${BROKER_URL} as ${clientId}…`);
    const c = window.mqtt.connect(BROKER_URL, {
      clientId,
      clean: true,
      keepalive: 30,
      reconnectPeriod: 3000,
      connectTimeout: 10_000,
    });
    client = c;
    setConn('connecting');

    c.on('connect', () => {
      if (client !== c) return;
      setConn('connected');
      log('sys', 'Connected to broker over TLS WebSocket.');
      subscribeAll(c);
    });
    c.on('reconnect', () => { if (client === c) setConn('reconnecting'); });
    c.on('offline', () => {
      if (client !== c) return;
      setConn('reconnecting', 'Offline — retrying…');
      log('warn', 'Broker connection lost; retrying every 3 s.');
    });
    c.on('error', (err) => {
      if (client !== c) return;
      log('err', `MQTT error: ${(err && err.message) || err}`);
    });
    c.on('message', (topic, payload) => { if (client === c) onMessage(topic, payload); });
  }

  function subscribeAll(c) {
    const subs = {
      [T.telA]: { qos: 0 },
      [T.telB]: { qos: 0 },
      [T.events]: { qos: 1 },
      [T.ackA]: { qos: 1 },
      [T.ackB]: { qos: 1 },
    };
    c.subscribe(subs, (err, granted) => {
      if (err) { log('err', `Subscribe failed: ${err.message}`); return; }
      const refused = (granted || []).filter((g) => g.qos === 128);
      if (refused.length) log('err', `Broker refused subscription: ${refused.map((g) => g.topic).join(', ')}`);
      else log('sys', `Subscribed under ${T.base}: ${Object.keys(subs).map(shortTopic).join(', ')}`);
    });
  }

  function teardown() {
    IDS.forEach(clearPending);
    if (client) {
      const c = client;
      client = null;
      try { c.end(true); } catch { /* ignore */ }
    }
  }
  function disconnect() {
    teardown();
    setConn('disconnected');
    log('sys', 'Disconnected by user.');
  }

  function readStale() {
    const v = Number($('staleSec').value);
    if (isNum(v) && v >= 1 && v <= 120) staleMs = v * 1000;
  }

  // ---------------------------------------------------------------------------
  // Incoming messages
  // ---------------------------------------------------------------------------
  function onMessage(topic, payload) {
    msgCount += 1;
    $('msgCount').textContent = String(msgCount);
    let m;
    try { m = JSON.parse(payload.toString()); } catch { reject(topic, 'payload is not valid JSON'); return; }
    if (!m || typeof m !== 'object' || Array.isArray(m)) { reject(topic, 'payload is not a JSON object'); return; }
    switch (topic) {
      case T.telA: handleTelemetry('A', m, topic); break;
      case T.telB: handleTelemetry('B', m, topic); break;
      case T.events: handleEvent(m, topic); break;
      case T.ackA: handleAck('A', m, topic); break;
      case T.ackB: handleAck('B', m, topic); break;
      default: reject(topic, 'unexpected topic');
    }
  }

  function reject(topic, reason) {
    rejCount += 1;
    $('rejCount').textContent = String(rejCount);
    const t = shortTopic(topic);
    const key = `${t}|${reason}`;
    const now = Date.now();
    if (now - (rejectSeen.get(key) || 0) >= REJECT_LOG_THROTTLE_MS) {
      rejectSeen.set(key, now);
      log('warn', `Rejected message on ${t}: ${reason}`);
    }
  }

  function validateTelemetry(id, m) {
    const cfg = DEVICES[id];
    if (m.device_id !== id) return `device_id must be "${id}" on this topic (got ${show(m.device_id)})`;
    if (m.sensor !== cfg.sensor) return `sensor must be "${cfg.sensor}" (got ${show(m.sensor)})`;
    if (!Number.isInteger(m.seq) || m.seq < 0) return `seq must be a non-negative integer (got ${show(m.seq)})`;
    if (!isNum(m.ts_ms)) return `ts_ms must be a number (got ${show(m.ts_ms)})`;
    if (m.ts_ms < EPOCH_MS_MIN) return 'ts_ms looks like uptime or seconds, not Unix epoch milliseconds';
    if (!cfg.statuses.includes(m.status)) return `status ${show(m.status)} is not allowed for edge ${id}`;
    for (const k of cfg.metrics) {
      const v = m[k.key];
      if (isNum(v)) continue;
      if (m.status === 'SENSOR_ERROR' && (v === null || v === undefined)) continue;
      return `${k.key} must be a finite number (got ${show(v)})`;
    }
    return null;
  }

  function handleTelemetry(id, m, topic) {
    const err = validateTelemetry(id, m);
    if (err) { reject(topic, err); return; }
    const s = state[id];
    const now = Date.now();
    if (s.lastSeq !== null) {
      if (m.seq > s.lastSeq + 1) s.gaps += m.seq - s.lastSeq - 1;
      else if (m.seq <= s.lastSeq) log('warn', `Edge ${id} seq went ${s.lastSeq} → ${m.seq} (edge restarted or duplicate).`);
    }
    if (s.last && s.last.status !== m.status) {
      log('rx', `Edge ${id} status ${s.last.status} → ${m.status} (telemetry seq ${m.seq})`);
    }
    s.lastSeq = m.seq;
    s.last = m;
    s.rxAt = now;
    s.count += 1;
    const v = {};
    for (const k of DEVICES[id].metrics) v[k.key] = isNum(m[k.key]) ? m[k.key] : NaN;
    s.series.push({ t: now, v });
    const cut = now - SERIES_KEEP_MS;
    while (s.series.length && s.series[0].t < cut) s.series.shift();
    renderCard(id);
    updateFreshness(id, now);
    scheduleDraw();
  }

  function handleEvent(m, topic) {
    if (m.device_id !== 'A' && m.device_id !== 'B') { reject(topic, `device_id must be "A" or "B" (got ${show(m.device_id)})`); return; }
    const cfg = DEVICES[m.device_id];
    if (typeof m.type !== 'string' || !cfg.statuses.includes(m.type)) {
      reject(topic, `event type ${show(m.type)} is not valid for edge ${m.device_id}`);
      return;
    }
    if (!isNum(m.ts_ms) || m.ts_ms < EPOCH_MS_MIN) { reject(topic, 'event ts_ms must be Unix epoch milliseconds'); return; }
    if (m.severity !== undefined && typeof m.severity !== 'string') { reject(topic, 'severity must be a string'); return; }
    if (m.detail !== undefined && typeof m.detail !== 'string') { reject(topic, 'detail must be a string'); return; }
    addTimelineItem(m, Date.now());
    log('rx', `Event from ${m.device_id}: ${m.type}${m.severity ? ` (${clip(m.severity, 20)})` : ''}`);
  }

  function handleAck(id, m, topic) {
    if (m.device_id !== id) { reject(topic, `device_id must be "${id}" on ack/${id} (got ${show(m.device_id)})`); return; }
    if (typeof m.command !== 'string') { reject(topic, 'ACK command must be a string'); return; }
    if (typeof m.success !== 'boolean') { reject(topic, 'ACK success must be true or false'); return; }
    const cfg = DEVICES[id];
    const p = pending[id];
    const now = Date.now();
    const lines = [];
    let kind = m.success ? 'ok' : 'fail';

    if (m.success) {
      const applied = {};
      const missing = [];
      for (const t of cfg.thresholds) {
        if (isNum(m[t.key])) applied[t.key] = m[t.key];
        else missing.push(t.key);
      }
      if (missing.length) {
        kind = 'fail';
        lines.push(`ACK says success, but applied value(s) missing: ${missing.join(', ')}.`);
      } else {
        state[id].thresholds = applied;
        renderThresholds(id);
        scheduleDraw();
        lines.push(`✓ Edge ${id} applied ${cfg.thresholds.map((t) => `${t.key} = ${applied[t.key]}`).join(', ')}`);
        if (p) {
          const diff = cfg.thresholds.filter((t) => Math.abs(applied[t.key] - p.payload[t.key]) > 1e-9).map((t) => t.key);
          if (diff.length) lines.push(`Note: applied value differs from requested for ${diff.join(', ')} (edge may clamp values).`);
        }
      }
    } else {
      const why = [m.error, m.reason, m.message].find((x) => typeof x === 'string');
      lines.push(`✗ Edge ${id} rejected ${clip(m.command, 40)}: ${why ? clip(why, 200) : '(no reason given in ACK)'}`);
    }

    if (p) {
      lines.push(`Round trip ${now - p.sentAt} ms · ACK ts_ms ${isNum(m.ts_ms) ? fmtClock(m.ts_ms) : 'n/a'}`);
      clearPending(id);
    } else {
      lines.push('Not requested by this dashboard tab (another client may have sent the command).');
    }
    showAck(id, kind, lines);
    log('ack', `ack/${id}: ${clip(JSON.stringify(m), 300)}`);
  }

  // ---------------------------------------------------------------------------
  // Outgoing control
  // ---------------------------------------------------------------------------
  function onControlSubmit(e, id) {
    e.preventDefault();
    const form = e.currentTarget;
    const payload = { command: 'SET_THRESHOLD', target: id };
    for (const t of DEVICES[id].thresholds) {
      const input = form.elements[t.key];
      const raw = input.value.trim();
      const v = Number(raw);
      if (raw === '' || !isNum(v) || v <= 0 || !input.checkValidity()) {
        showAck(id, 'fail', [`${t.key} must be a positive number between ${input.min} and ${input.max}.`]);
        input.focus();
        return;
      }
      payload[t.key] = v;
    }
    sendControl(id, payload);
  }

  function sendControl(id, payload) {
    if (!client || !client.connected || !T) { showAck(id, 'fail', ['Not connected to the broker.']); return; }
    clearPending(id);
    const body = JSON.stringify(payload);
    const sentAt = Date.now();
    pending[id] = {
      payload,
      sentAt,
      timer: setTimeout(() => {
        pending[id] = null;
        showAck(id, 'fail', [
          `No ACK from edge ${id} within ${ACK_TIMEOUT_MS / 1000} s.`,
          'Check that the edge is running, online, and uses the same PROJECT_ID.',
        ]);
        log('warn', `No ACK from edge ${id} within ${ACK_TIMEOUT_MS / 1000} s.`);
      }, ACK_TIMEOUT_MS),
    };
    showAck(id, 'pending', [`Sent ${payload.command} → ${id}. Waiting for ACK on ack/${id}…`, body]);
    log('tx', `control → ${id}: ${body}`);
    client.publish(T.control, body, { qos: 1, retain: false }, (err) => {
      if (!err) return;
      clearPending(id);
      showAck(id, 'fail', [`Publish failed: ${err.message}`]);
      log('err', `Publish to control failed: ${err.message}`);
    });
  }

  function clearPending(id) {
    const p = pending[id];
    if (p) { clearTimeout(p.timer); pending[id] = null; }
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------
  function renderCard(id) {
    const s = state[id];
    const m = s.last;
    for (const k of DEVICES[id].metrics) {
      $(`v${id}_${k.key}`).textContent = m ? fmtNum(m[k.key], k.digits) : '—';
      $(`u${id}_${k.key}`).textContent = k.unit;
    }
    const st = $(`status${id}`);
    st.textContent = m ? m.status : '—';
    st.dataset.status = m ? m.status : '';
    $(`seq${id}`).textContent = m ? `${m.seq}  (${s.count} received)` : '—';
    $(`ts${id}`).textContent = m
      ? `${fmtClock(m.ts_ms)}  · rx − ts ≈ ${signed(s.rxAt - m.ts_ms)} ms (latency + clock skew)`
      : '—';
    $(`gap${id}`).textContent = String(s.gaps);
    $(`raw${id}`).textContent = m ? JSON.stringify(m, null, 2) : '—';
  }

  function renderThresholds(id) {
    const thr = state[id].thresholds;
    $(`thr${id}`).textContent = thr
      ? DEVICES[id].thresholds.map((t) => `${t.key} = ${thr[t.key]}`).join(' · ')
      : 'unknown until the edge sends an ACK';
  }

  function updateFreshness(id, now) {
    const s = state[id];
    let f = 'none';
    let label = 'No data yet';
    if (s.rxAt) {
      const age = now - s.rxAt;
      if (age > staleMs) { f = 'stale'; label = `Stale · ${fmtAge(age)}`; }
      else { f = 'fresh'; label = 'Fresh'; }
      $(`rx${id}`).textContent = `${fmtClock(s.rxAt)} (${fmtAge(age)})`;
    } else {
      $(`rx${id}`).textContent = '—';
    }
    $(`card${id}`).dataset.fresh = f;
    const chip = $(`fresh${id}`);
    chip.textContent = label;
    chip.dataset.fresh = f;
    if (f !== s.freshState) {
      if (f === 'stale') log('warn', `Edge ${id} is stale: no telemetry for more than ${staleMs / 1000} s.`);
      else if (f === 'fresh' && s.freshState === 'stale') log('sys', `Edge ${id} is fresh again.`);
      s.freshState = f;
    }
  }

  function showAck(id, kind, lines) {
    const box = $(`ack${id}`);
    box.dataset.kind = kind;
    box.replaceChildren(...lines.map((l) => el('div', null, l)));
  }

  function addTimelineItem(m, rxAt) {
    const list = $('events');
    const empty = list.querySelector('.empty');
    if (empty) empty.remove();
    const li = el('li', 'ev');
    li.dataset.type = m.type;
    const sev = typeof m.severity === 'string' ? m.severity.toUpperCase() : '';
    li.dataset.sev = /^[A-Z_]{1,20}$/.test(sev) ? sev : '';
    const head = el('div', 'ev-head');
    head.append(el('span', 'dev-tag small', m.device_id), el('span', 'ev-type', m.type));
    if (m.severity) head.append(el('span', 'ev-sev', clip(m.severity, 20)));
    head.append(el('time', 'ev-time', fmtClock(m.ts_ms)));
    li.append(head);
    if (m.detail) li.append(el('p', 'ev-detail', clip(m.detail, 240)));
    li.append(el('p', 'ev-meta', `Edge ${m.device_id} · ${DEVICES[m.device_id].name} · received ${fmtClock(rxAt)}`));
    list.prepend(li);
    while (list.children.length > MAX_TIMELINE) list.lastElementChild.remove();
    eventCount += 1;
    $('eventCount').textContent = String(eventCount);
  }

  function clearTimeline() {
    const list = $('events');
    list.replaceChildren(el('li', 'empty', 'No events received yet.'));
    eventCount = 0;
    $('eventCount').textContent = '0';
  }

  function log(kind, text) {
    const list = $('log');
    const li = el('li', `log-${kind}`);
    li.append(el('time', null, fmtClock(Date.now())), el('span', 'log-kind', kind.toUpperCase()), el('span', 'log-text', text));
    list.prepend(li);
    while (list.children.length > MAX_LOG) list.lastElementChild.remove();
  }

  function resetData() {
    IDS.forEach((id) => { state[id] = blank(); });
    msgCount = 0;
    rejCount = 0;
    rejectSeen.clear();
    $('msgCount').textContent = '0';
    $('rejCount').textContent = '0';
    clearTimeline();
    IDS.forEach((id) => {
      renderCard(id);
      renderThresholds(id);
      updateFreshness(id, Date.now());
      showAck(id, 'idle', ['No command sent yet.']);
    });
    scheduleDraw();
  }

  // ---------------------------------------------------------------------------
  // Charts (canvas, no library). Only received samples are plotted.
  // ---------------------------------------------------------------------------
  function buildLegend(id) {
    const box = $(`legend${id}`);
    box.replaceChildren();
    for (const k of DEVICES[id].metrics) {
      const b = el('button', 'legend-item');
      b.type = 'button';
      b.setAttribute('aria-pressed', 'true');
      b.title = `Show/hide ${k.label}`;
      const sw = el('span', 'swatch');
      sw.style.background = `var(${k.color})`;
      b.append(sw, el('span', null, k.label));
      b.addEventListener('click', () => {
        const h = hidden[id];
        if (h.has(k.key)) h.delete(k.key); else h.add(k.key);
        b.setAttribute('aria-pressed', String(!h.has(k.key)));
        scheduleDraw();
      });
      box.append(b);
    }
    box.append(el('span', 'legend-note', 'dashed line = threshold applied by edge (from ACK)'));
  }

  let drawQueued = false;
  function scheduleDraw() {
    if (drawQueued) return;
    drawQueued = true;
    requestAnimationFrame(() => {
      drawQueued = false;
      IDS.forEach(drawChart);
    });
  }

  function drawChart(id) {
    const canvas = $(`chart${id}`);
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    if (!w || !h) return;
    const W = Math.round(w * dpr);
    const H = Math.round(h * dpr);
    if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const css = getComputedStyle(document.documentElement);
    const col = (name) => css.getPropertyValue(name).trim() || '#888';
    const cfg = DEVICES[id];
    const s = state[id];
    const hid = hidden[id];
    const P = { l: 46, r: 10, t: 10, b: 22 };
    const pw = Math.max(10, w - P.l - P.r);
    const ph = Math.max(10, h - P.t - P.b);
    const now = Date.now();
    const t0 = now - CHART_WINDOW_MS;
    const active = cfg.metrics.filter((k) => !hid.has(k.key));
    const pts = s.series.filter((p) => p.t >= t0 - staleMs);

    let top = 0;
    for (const p of pts) for (const k of active) { const v = p.v[k.key]; if (isNum(v) && v > top) top = v; }
    const thrLines = [];
    if (s.thresholds) {
      for (const t of cfg.thresholds) {
        const k = cfg.metrics.find((mm) => mm.key === t.metric);
        const v = s.thresholds[t.key];
        if (k && !hid.has(k.key) && isNum(v)) { thrLines.push({ v, color: k.color }); if (v > top) top = v; }
      }
    }
    const yMax = niceCeil(top);

    // Grid + axis labels
    ctx.font = '11px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
    ctx.lineWidth = 1;
    ctx.strokeStyle = col('--grid');
    ctx.fillStyle = col('--muted');
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let i = 0; i <= 4; i += 1) {
      const y = Math.round(P.t + ph * (1 - i / 4)) + 0.5;
      ctx.beginPath(); ctx.moveTo(P.l, y); ctx.lineTo(P.l + pw, y); ctx.stroke();
      ctx.fillText(fmtTick((yMax * i) / 4), P.l - 6, y);
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i <= 4; i += 1) {
      const secs = Math.round((CHART_WINDOW_MS / 1000) * (1 - i / 4));
      ctx.fillText(secs === 0 ? 'now' : `−${secs}s`, P.l + (pw * i) / 4, P.t + ph + 6);
    }

    if (!pts.length) {
      ctx.textBaseline = 'middle';
      ctx.fillText(s.rxAt ? 'No telemetry in the last 60 s' : 'Waiting for real telemetry…', P.l + pw / 2, P.t + ph / 2);
      return;
    }

    const X = (t) => P.l + ((t - t0) / CHART_WINDOW_MS) * pw;
    const Y = (v) => P.t + ph * (1 - v / yMax);
    ctx.save();
    ctx.beginPath();
    ctx.rect(P.l, P.t - 3, pw + 3, ph + 6);
    ctx.clip();

    // Applied thresholds (only known from ACKs)
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1.25;
    for (const L of thrLines) {
      ctx.strokeStyle = col(L.color);
      ctx.globalAlpha = 0.85;
      const y = Y(L.v);
      ctx.beginPath(); ctx.moveTo(P.l, y); ctx.lineTo(P.l + pw, y); ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.globalAlpha = 1;

    // Series. Lines break across gaps longer than the stale window or on missing values.
    ctx.lineWidth = 1.75;
    ctx.lineJoin = 'round';
    for (const k of active) {
      ctx.strokeStyle = col(k.color);
      ctx.beginPath();
      let pen = false;
      let prevT = 0;
      for (const p of pts) {
        const v = p.v[k.key];
        if (!isNum(v)) { pen = false; continue; }
        const x = X(p.t);
        const y = Y(v);
        if (!pen || p.t - prevT > staleMs) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        pen = true;
        prevT = p.t;
      }
      ctx.stroke();
      const lastP = pts[pts.length - 1];
      if (isNum(lastP.v[k.key])) {
        ctx.fillStyle = col(k.color);
        ctx.beginPath();
        ctx.arc(X(lastP.t), Y(lastP.v[k.key]), 2.75, 0, Math.PI * 2);
        ctx.fill();
      }
    }
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------------------
  function tick() {
    const now = Date.now();
    IDS.forEach((id) => updateFreshness(id, now));
    scheduleDraw();
  }

  function init() {
    IDS.forEach((id) => {
      buildLegend(id);
      renderCard(id);
      renderThresholds(id);
      updateFreshness(id, Date.now());
      showAck(id, 'idle', ['No command sent yet.']);
    });

    const qp = new URLSearchParams(window.location.search).get('project');
    $('projectId').value = qp && PROJECT_ID_RE.test(qp) ? qp : (safeStore.get(STORAGE_KEY) || '');

    $('connectForm').addEventListener('submit', (e) => { e.preventDefault(); connect(); });
    $('disconnectBtn').addEventListener('click', disconnect);
    $('staleSec').addEventListener('change', () => { readStale(); tick(); });
    $('formA').addEventListener('submit', (e) => onControlSubmit(e, 'A'));
    $('formB').addEventListener('submit', (e) => onControlSubmit(e, 'B'));
    $('clearEvents').addEventListener('click', clearTimeline);
    $('clearLog').addEventListener('click', () => { $('log').replaceChildren(); });

    if ('ResizeObserver' in window) {
      const ro = new ResizeObserver(scheduleDraw);
      IDS.forEach((id) => ro.observe($(`chart${id}`)));
    } else {
      window.addEventListener('resize', scheduleDraw);
    }
    const mq = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
    if (mq && mq.addEventListener) mq.addEventListener('change', scheduleDraw);
    window.addEventListener('beforeunload', teardown);

    setConn('disconnected');
    log('sys', 'Dashboard ready. Enter the same PROJECT_ID used by both edges, then connect.');
    if (!window.mqtt) showConnError('MQTT.js did not load from the CDN. Check the internet connection, then reload.');
    setInterval(tick, 1000);
    scheduleDraw();
  }

  init();
})();
