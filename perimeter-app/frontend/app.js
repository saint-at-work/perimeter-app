// ---------- SHARED MAP ----------
const map = L.map('map', { zoomControl: false }).setView([6.5244, 3.3792], 17);
L.control.zoom({ position: 'bottomright' }).addTo(map);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributor', maxZoom: 19
}).addTo(map);

if (navigator.geolocation) {
  navigator.geolocation.getCurrentPosition(pos => {
    map.setView([pos.coords.latitude, pos.coords.longitude], 17);
  }, () => { }, { enableHighAccuracy: true, timeout: 5000 });
}

function log(message, cls) {
  const row = document.createElement('div');
  row.className = 'log-entry' + (cls ? ' ' + cls : '');
  const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  row.innerHTML = `<span class="t mono">${time}</span><span class="m">${message}</span>`;
  document.getElementById('logList').prepend(row);
}

// ---------- TAB SWITCHING ----------
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const target = tab.dataset.tab;
    document.getElementById('panel-organizer').classList.toggle('hidden', target !== 'organizer');
    document.getElementById('panel-attendee').classList.toggle('hidden', target !== 'attendee');
    document.getElementById('organizerToolbar').classList.toggle('hidden', target !== 'organizer');
  });
});

// =====================================================================
// ORGANIZER MODE — walk the boundary, drop GPS markers, create event
// =====================================================================
(function organizer() {
  let vertices = [];
  let vertexMarkers = [];
  let polygonLayer = null;
  let liveMarker = null;
  let accuracyCircle = null;
  let watchId = null;
  let lastFix = null;
  let surveying = false;

  const els = {
    btnStart: document.getElementById('btnStart'),
    btnMark: document.getElementById('btnMark'),
    btnFinish: document.getElementById('btnFinish'),
    btnClear: document.getElementById('btnClear'),
    btnCreateEvent: document.getElementById('btnCreateEvent'),
    posReadout: document.getElementById('posReadout'),
    accReadout: document.getElementById('accReadout'),
    accBadge: document.getElementById('accBadge'),
    vertexCount: document.getElementById('vertexCount'),
    vertexList: document.getElementById('vertexList'),
    thresholdSlider: document.getElementById('thresholdSlider'),
    thresholdVal: document.getElementById('thresholdVal'),
    eventName: document.getElementById('eventName'),
    apiBase: document.getElementById('apiBase'),
    createdEventBox: document.getElementById('createdEventBox'),
    createdEventId: document.getElementById('createdEventId'),
  };

  els.thresholdSlider.addEventListener('input', () => {
    els.thresholdVal.textContent = els.thresholdSlider.value + 's';
  });

  els.btnStart.addEventListener('click', () => {
    if (!navigator.geolocation) { log('Geolocation not supported', 'exit'); return; }
    resetSurvey();
    surveying = true;
    els.btnStart.disabled = true;
    els.btnMark.disabled = false;
    watchId = navigator.geolocation.watchPosition(onPosition, onGeoError, {
      enableHighAccuracy: true, maximumAge: 1000, timeout: 15000
    });
    log('Boundary walk started');
  });

  function onPosition(pos) {
    const { latitude: lat, longitude: lng, accuracy: acc } = pos.coords;
    lastFix = { lat, lng, acc };
    els.posReadout.textContent = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    els.accReadout.textContent = `±${acc.toFixed(0)} m`;
    els.accReadout.className = 'v mono' + (acc > 20 ? ' bad' : acc > 10 ? ' warn' : '');
    els.accBadge.textContent = `GPS: ±${acc.toFixed(0)}m`;

    if (!liveMarker) {
      liveMarker = L.circleMarker([lat, lng], { radius: 7, color: '#ffb020', fillColor: '#ffb020', fillOpacity: 0.95, weight: 2 }).addTo(map);
      map.setView([lat, lng], 18);
    } else {
      liveMarker.setLatLng([lat, lng]);
    }
    if (!accuracyCircle) {
      accuracyCircle = L.circle([lat, lng], { radius: acc, color: '#ffb020', weight: 1, fillOpacity: 0.08 }).addTo(map);
    } else {
      accuracyCircle.setLatLng([lat, lng]);
      accuracyCircle.setRadius(acc);
    }
  }

  function onGeoError(err) { log('GPS error: ' + err.message, 'exit'); }

  els.btnMark.addEventListener('click', () => {
    if (!lastFix) { log('No GPS fix yet', 'exit'); return; }
    vertices.push({ lat: lastFix.lat, lng: lastFix.lng, acc: lastFix.acc });
    const marker = L.circleMarker([lastFix.lat, lastFix.lng], { radius: 6, color: '#3ee08c', fillColor: '#3ee08c', fillOpacity: 1, weight: 2 }).addTo(map);
    vertexMarkers.push(marker);
    redrawPolygon();
    els.vertexCount.textContent = vertices.length;
    renderVertexList();
    log(`Marker ${vertices.length} dropped (±${lastFix.acc.toFixed(0)}m)`, 'mark');
    if (vertices.length >= 3) els.btnFinish.disabled = false;
  });

  function renderVertexList() {
    els.vertexList.innerHTML = vertices.map((v, i) =>
      `<div class="vertex-item"><span><span class="n">${i + 1}</span>${v.lat.toFixed(5)}, ${v.lng.toFixed(5)}</span><span class="acc">±${v.acc.toFixed(0)}m</span></div>`
    ).join('');
  }

  function redrawPolygon() {
    if (polygonLayer) map.removeLayer(polygonLayer);
    if (vertices.length < 2) return;
    polygonLayer = L.polygon(vertices.map(v => [v.lat, v.lng]), {
      color: '#3ee08c', weight: 2, fillColor: '#3ee08c', fillOpacity: 0.08, dashArray: surveying ? '4 6' : null
    }).addTo(map);
  }

  els.btnFinish.addEventListener('click', () => {
    surveying = false;
    els.btnMark.disabled = true;
    els.btnFinish.disabled = true;
    if (watchId !== null) { navigator.geolocation.clearWatch(watchId); watchId = null; }
    redrawPolygon();
    log('Boundary closed with ' + vertices.length + ' points');
    els.btnCreateEvent.disabled = false;
  });

  els.btnCreateEvent.addEventListener('click', async () => {
    const name = els.eventName.value.trim() || 'Untitled Event';
    const threshold = parseInt(els.thresholdSlider.value, 10);
    const polygon = vertices.map(v => [v.lat, v.lng]);
    const base = els.apiBase.value.replace(/\/$/, '');

    try {
      const res = await fetch(`${base}/events`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, polygon, threshold_seconds: threshold })
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      els.createdEventBox.classList.remove('hidden');
      els.createdEventId.textContent = data.id;
      log(`Event created — ID ${data.id}`, 'confirm');
    } catch (err) {
      log('Failed to create event: ' + err.message, 'exit');
    }
  });

  els.btnClear.addEventListener('click', () => { resetSurvey(); fullReset(); });

  function resetSurvey() {
    vertices = [];
    vertexMarkers.forEach(m => map.removeLayer(m));
    vertexMarkers = [];
    if (polygonLayer) map.removeLayer(polygonLayer);
    polygonLayer = null;
    els.vertexCount.textContent = '0';
    els.vertexList.innerHTML = '';
    els.btnFinish.disabled = true;
    els.btnCreateEvent.disabled = true;
    els.createdEventBox.classList.add('hidden');
  }

  function fullReset() {
    els.btnStart.disabled = false;
    els.btnMark.disabled = true;
    if (watchId !== null) { navigator.geolocation.clearWatch(watchId); watchId = null; }
    if (liveMarker) { map.removeLayer(liveMarker); liveMarker = null; }
    if (accuracyCircle) { map.removeLayer(accuracyCircle); accuracyCircle = null; }
    lastFix = null;
    els.posReadout.textContent = 'no fix';
    els.accReadout.textContent = '—';
    els.accBadge.textContent = 'GPS: —';
  }
})();

// =====================================================================
// ATTENDEE MODE — ping the backend on an interval, show dwell status
// =====================================================================
(function attendee() {
  const els = {
    apiBase: document.getElementById('apiBaseAttendee'),
    eventId: document.getElementById('attendEventId'),
    userId: document.getElementById('attendUserId'),
    btnJoin: document.getElementById('btnJoin'),
    stateText: document.getElementById('stateText'),
    stateDetail: document.getElementById('stateDetail'),
    ringFg: document.getElementById('ringFg'),
    ringSweep: document.getElementById('ringSweep'),
    insideReadout: document.getElementById('insideReadout'),
    dwellReadout: document.getElementById('dwellReadout'),
  };
  const RING_CIRCUMFERENCE = 188.5;
  let watchId = null;
  let confirmed = false;
  let attendeeMarker = null;

  function setState(kind, detail) {
    els.stateText.className = 'state ' + kind;
    els.stateText.textContent = kind.toUpperCase();
    els.stateDetail.textContent = detail;
  }

  function updateRing(fraction) {
    const clamped = Math.max(0, Math.min(1, fraction));
    els.ringFg.style.strokeDashoffset = RING_CIRCUMFERENCE * (1 - clamped);
    els.ringFg.style.stroke = confirmed ? '#3ee08c' : (clamped > 0 ? '#ffb020' : '#3ee08c');
  }

  els.btnJoin.addEventListener('click', () => {
    const eventId = els.eventId.value.trim();
    const userId = els.userId.value.trim();
    if (!eventId || !userId) { log('Enter both event ID and your name', 'exit'); return; }
    if (!navigator.geolocation) { log('Geolocation not supported', 'exit'); return; }

    confirmed = false;
    els.ringSweep.classList.add('active');
    setState('tracking', 'Acquiring GPS fix…');
    els.btnJoin.disabled = true;
    log(`Check-in started for "${userId}" on event ${eventId}`);

    watchId = navigator.geolocation.watchPosition(
      pos => sendPing(eventId, userId, pos),
      err => log('GPS error: ' + err.message, 'exit'),
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 }
    );
  });

  async function sendPing(eventId, userId, pos) {
    if (confirmed) return;
    const { latitude: lat, longitude: lng, accuracy } = pos.coords;
    const base = els.apiBase.value.replace(/\/$/, '');

    if (!attendeeMarker) {
      attendeeMarker = L.circleMarker([lat, lng], { radius: 7, color: '#ffb020', fillColor: '#ffb020', fillOpacity: 0.95, weight: 2 }).addTo(map);
      map.setView([lat, lng], 18);
    } else {
      attendeeMarker.setLatLng([lat, lng]);
    }

    try {
      const res = await fetch(`${base}/events/${eventId}/ping`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, lat, lng, accuracy })
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();

      els.insideReadout.textContent = data.inside ? 'YES' : 'NO';
      els.insideReadout.className = 'v mono' + (data.inside ? '' : ' bad');
      els.dwellReadout.textContent = Math.floor(data.dwell_seconds) + 's';
      updateRing(data.dwell_seconds / data.threshold_seconds);

      if (data.confirmed) {
        confirmed = true;
        setState('confirmed', 'Attendance confirmed at ' + new Date().toLocaleTimeString());
        log('ATTENDANCE CONFIRMED', 'confirm');
        updateRing(1);
        if (watchId !== null) { navigator.geolocation.clearWatch(watchId); watchId = null; }
      } else if (data.inside) {
        const remaining = Math.max(0, Math.ceil(data.threshold_seconds - data.dwell_seconds));
        setState('tracking', `${remaining}s to confirmation`);
      } else {
        setState('outside', 'Outside venue boundary');
      }
    } catch (err) {
      log('Ping failed: ' + err.message, 'exit');
    }
  }
})();
