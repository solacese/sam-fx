'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const rendered = new Map();
function setHTML(id, value) {
  if(rendered.get(id) !== value) { $(id).innerHTML = value; rendered.set(id, value); }
}
let state = null, selected = null, books = {}, question = null, lastTime = '';
const pill = value => `<span class="pill ${esc(value.toLowerCase())}">${esc(value)}</span>`;
const time = value => value ? new Date(value).toLocaleTimeString('en-GB', {timeZone:'UTC'}) + ' UTC' : '—';
const selectedIncident = () => state?.incidents.find(i => i.incident_id === selected);
function error(message) { $('error').hidden = !message; $('error').textContent = message; }
async function post(path) {
  try { if(window.SamFxDemo) return await window.SamFxDemo.post(path); const res = await fetch(path, {method:'POST'}); if (!res.ok) throw new Error((await res.json()).detail || 'Request failed'); error(''); return await res.json(); }
  catch (e) { error(e.message); return null; }
}
document.querySelectorAll('[data-scenario]').forEach(button => button.addEventListener('click', async () => {
  button.disabled = true; selected = null; const result = await post('/api/scenarios/' + button.dataset.scenario); button.disabled = false; if(result) render(result);
}));
$('recover').addEventListener('click', async () => { const result = await post('/api/recover'); if(result) render(result); });
document.querySelectorAll('[data-question]').forEach(button => button.addEventListener('click', () => { question = button.dataset.question; renderChat(); }));
$('incidents').addEventListener('click', async event => {
  const action = event.target.closest('[data-action]');
  if(action) { action.disabled = true; await post(`/api/incidents/${action.dataset.id}/${action.dataset.action}`); action.disabled = false; return; }
  const row = event.target.closest('[data-incident]');
  if(row) { selected = row.dataset.incident; render(state); }
});
function renderChat() {
  if(!state || !question) return;
  const incident = selectedIncident(), assessment = incident?.assessment || (!incident ? state.assessment : null);
  const answers = {
    changed: assessment?.assessment || 'No confirmed event explanation is available yet. Service health is checked independently of market volatility.',
    impact: incident?.impact || 'The demo observes two EUR/USD consumer paths. It does not measure customer orders, execution quality or financial impact.',
    next: assessment?.suggested_next_investigation || 'Compare fresh telemetry across regions. Confirm the affected service before escalating; missing data does not prove an outage.'
  };
  $('chat-answer').textContent = answers[question];
  document.querySelectorAll('[data-question]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.question === question)));
}
function render(s) {
  state = s;
  if(!selected && s.last_change) selected = s.incidents.find(i => i.correlation_id === s.last_change.correlation_id)?.incident_id || null;
  $('clock').textContent = time(s.snapshot?.timestamp);
  for(const [id, value] of [['market-status',s.market_condition], ['service-status',s.service_condition]]) { $(id).textContent = value; $(id).className = value.toLowerCase(); }
  $('incident-count').textContent = s.incidents.filter(i => ['OPEN','ACKNOWLEDGED'].includes(i.status)).length;
  $('investigations').textContent = `${s.pending_investigations} pending · ${s.completed_investigations} done · ${s.failed_investigations} failed`;
  $('scenario-status').textContent = s.running ? 'Scenario running · auto-resets after 24 observations' : 'Normal stream running';
  document.querySelectorAll('[data-scenario]').forEach(b => b.setAttribute('aria-pressed', String(s.running && s.scenario === b.dataset.scenario)));
  const p = s.snapshot;
  if(p) {
    $('mid').textContent = p.mid.toFixed(5);
    $('bid').textContent = p.bid.toFixed(5); $('ask').textContent = p.ask.toFixed(5);
    $('spread').textContent = ((p.ask-p.bid)*10000).toFixed(1) + ' pips';
    if(lastTime !== p.timestamp) { lastTime = p.timestamp; $('mid').classList.remove('update'); void $('mid').offsetWidth; $('mid').classList.add('update'); }
    window.SamFxChart.update(p, s.price_history || []);
    $('stats').innerHTML = [['Volatility','volatility'],['Spread','spread'],['Quote rate','quote_rate']].map(([label,key]) => `<div class="${p.zscores[key]>=3?'elevated':''}">${label}<strong>${p.zscores[key].toFixed(1)}σ</strong></div>`).join('');
  }
  $('services').innerHTML = s.services.map(h => {
    const o = h.observation, unknown = h.status === 'UNKNOWN', age = Math.max(0,(Date.parse(h.observed_at)-Date.parse(o.timestamp))/1000);
    return `<tr><td>${esc(o.service_id)}<small>${esc(o.region.replace('_',' '))} · ${esc(o.delivery_mode)}</small></td><td>${pill(h.status)}<small>${h.confirmed?'Confirmed':'Confirming…'}</small></td><td>${unknown?'—':o.quote_age_ms.toFixed(0)+' ms'}</td><td>${unknown?'—':`${o.ingress_rate} → ${o.egress_rate}`}</td><td>${unknown?'—':o.p99_latency_ms+' ms'}</td><td>${unknown?'—':`${o.discard_delta} / ${o.sequence_gap_delta}`}</td><td>${age.toFixed(0)} s</td></tr>`;
  }).join('');
  $('journal-count').textContent = `${s.incidents.length} record${s.incidents.length===1?'':'s'}`;
  setHTML('incidents', s.incidents.length ? s.incidents.map(i => `<article class="incident ${selected===i.incident_id?'selected':''}" data-incident="${esc(i.incident_id)}"><div class="incident-top">${pill(i.status)}<span class="label">${i.severity} · ${time(i.opened_at)}</span></div><button class="incident-select" data-incident="${esc(i.incident_id)}">${esc(i.title)} ↗</button><p>${esc(i.impact)}</p>${i.status==='OPEN'?`<button data-action="acknowledge" data-id="${esc(i.incident_id)}">Acknowledge</button>`:i.status==='RECOVERED'?`<button data-action="resolve" data-id="${esc(i.incident_id)}">Resolve incident</button>`:''}</article>`).join('') : '<div class="empty">No service incidents.<br>Market stress alone is an advisory.<br>A service failure can trigger even in a quiet market.</div>');
  const incident = selectedIncident();
  const a = incident?.assessment || (!incident ? s.assessment : null);
  const change = incident ? null : s.last_change;
  const book = incident ? books[incident.runbook] : null;
  $('explanation-mode').textContent = a ? (a.model.includes('fallback') ? 'Prepared rules' : 'Model explanation') : 'Awaiting evidence';
  setHTML('evidence', `${incident?`<div class="meta"><span>${esc(incident.owner)}</span><span>${esc(incident.region)}</span><span>${esc(incident.correlation_id.slice(0,8))}</span><span>Frozen at ${time(incident.opened_at)}</span></div>`:change?`<div class="meta"><span>${change.event==='FX_REGIME_CHANGE'?'Market advisory':'Service incident'}</span><span>${esc(change.correlation_id.slice(0,8))}</span></div>`:''}
    <h3>${esc(a?.assessment || (incident ? incident.title : 'Ready for the next confirmed event.'))}</h3>
    ${a?`<div class="meta"><span>${esc(a.likely_cause)}</span><span>${window.SamFxDemo?'Prepared replay':a.latency_ms+' ms worker time'}</span><span>${a.degraded?'Fallback used':a.model==='deterministic-fallback'?'Prepared rules':'Configured provider'}</span></div><ul>${a.evidence.map(e=>`<li>${esc(e)}</li>`).join('')}</ul><h3>Next investigation</h3><p>${esc(a.suggested_next_investigation)}</p>`: `<p>${esc(incident?.impact || 'Numeric monitoring runs every second. Confirmed service incidents create a frozen evidence package for explanation. Select an incident to inspect its owner and runbook.')}</p>${incident?`<ul>${incident.evidence.map(e=>`<li>${esc(e)}</li>`).join('')}</ul>`:''}`}
    ${book?`<h3>Runbook · ${esc(book.title)}</h3><ol>${book.checks.map(c=>`<li>${esc(c)}</li>`).join('')}</ol>`:''}
    ${incident?.audit.length?`<details><summary>Lifecycle history</summary><ul>${incident.audit.map(e=>`<li>${esc(e)}</li>`).join('')}</ul></details>`:''}
    <p class="limits">${esc(a?.limitations.join(' ') || 'Synthetic topology and thresholds. No independent investigation tools are connected. No client impact is inferred.')}</p>`);
  $('timeline').innerHTML = s.timeline.map(e=>`<li>${time(e.timestamp)} · ${esc(e.label)}</li>`).join('');
  $('timing').textContent = `${s.observations} observations · ${s.explanation_latency_ms == null ? 'No completed explanation' : s.explanation_latency_ms+' ms latest worker time (excludes detection/queue)'}`;
  if(window.SamFxDemo) { $('timing').textContent = `${s.observations} replay observations · no live latency measurement`; if(!window.SamFxDemo.storageAvailable) error('Browser storage is unavailable. Export handover to keep this session.'); }
  window.SamFxAiops.render(s, a, incident);
  renderChat();
}
if(window.SamFxDemo) {
  books = window.SamFxDemo.runbooks;
  window.SamFxDemo.start(s => { $('connection').textContent='● BROWSER DEMO'; render(s); });
} else {
fetch('/api/runbooks').then(r=>r.json()).then(data=>{ books=data; if(state)render(state); }).catch(()=>error('Runbooks could not be loaded.'));
const stream = new EventSource('/api/events');
stream.onmessage = event => { $('connection').textContent=JSON.parse(event.data).llm_enabled?'● SIM FEEDS · LIVE LLM':'● SIM FEEDS · PREPARED'; render(JSON.parse(event.data)); };
stream.onerror = () => { window.SamFxChart.disconnect(); $('connection').textContent='○ RECONNECTING'; $('service-status').textContent='UNKNOWN'; $('service-status').className='unknown'; };

}
