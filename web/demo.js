/* GitHub Pages adapter. Replays offline Python-generated detector evidence.
   No requests, credentials, model calls or brokerage connection. */
'use strict';
(() => {
  if (!window.SamFxFixtures) return;
  const fixtures = window.SamFxFixtures, storageKey = 'sam-fx-pages-journal-v1';
  const copy = value => JSON.parse(JSON.stringify(value));
  let journal = [], evidence = [], listener, value, clipName = 'baseline', index = 0;
  let ids = new Map(), offset = 0, count = 0, completed = 0, lastChange = null, assessment = null;
  let baselineClip = 'baseline';
  let timeline = [], seen = new Set(), recovery = new Map(), storageAvailable = true;
  try {
    const saved = JSON.parse(localStorage.getItem(storageKey) || '{}');
    if(saved.version === 1 && Array.isArray(saved.incidents) && Array.isArray(saved.evidence)) {
      journal = saved.incidents; evidence = saved.evidence;
    }
  } catch { storageAvailable = false; }
  function save() {
    try { localStorage.setItem(storageKey, JSON.stringify({version:1,incidents:journal,evidence})); }
    catch { storageAvailable = false; }
  }
  function rebase(item) {
    if(Array.isArray(item)) return item.map(rebase);
    if(item && typeof item === 'object') return Object.fromEntries(Object.entries(item).map(([k,v])=>[k,rebase(v)]));
    if(typeof item !== 'string') return item;
    return item.replace(/\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)/g,
      date => new Date(Date.parse(date)+offset).toISOString()).replace(
      /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/g, id => {
        if(!ids.has(id)) ids.set(id, crypto.randomUUID()); return ids.get(id);
      });
  }
  function begin(name) {
    if(name==='baseline') name=baselineClip;
    clipName = name; index = 0; ids = new Map();
    offset = Date.now() - Date.parse(fixtures.clips[name][0].snapshot.timestamp);
  }
  function tick() {
    const frames = fixtures.clips[clipName];
    if(index >= frames.length) begin('baseline');
    const frame = rebase(copy(fixtures.clips[clipName][index++]));
    count++;
    if(frame.last_change && !seen.has(frame.last_change.correlation_id)) {
      seen.add(frame.last_change.correlation_id);
      lastChange = frame.last_change; assessment = frame.assessment; completed++;
      evidence.unshift({event:lastChange, status:'prepared-replay', assessment});
      evidence = evidence.slice(0,100);
      timeline.unshift({timestamp:new Date().toISOString(),kind:'signal',label:'Prepared replay: evidence confirmed and explanation available'});
      for(const incoming of frame.incidents) {
        const active = journal.find(i=>i.service_id===incoming.service_id && ['OPEN','ACKNOWLEDGED'].includes(i.status));
        if(!active && !journal.some(i=>i.incident_id===incoming.incident_id)) {
          incoming.audit = [`${incoming.opened_at} Opened after three abnormal replay observations.`];
          journal.unshift(incoming);
        }
      }
      save();
    }
    for(const incident of journal) {
      if(!['OPEN','ACKNOWLEDGED'].includes(incident.status)) continue;
      const service = frame.services.find(h=>h.observation.service_id===incident.service_id);
      const healthy = incident.runbook==='aiops' ? (frame.aiops?.offmarket ? frame.aiops.offmarket.status==='WITHIN_BAND' : frame.aiops?.status==='WITHIN_LIMITS') : service?.status==='HEALTHY';
      const samples = healthy ? (recovery.get(incident.incident_id)||0)+1 : 0;
      recovery.set(incident.incident_id,samples);
      if(samples >= 5) {
        incident.status='RECOVERED'; incident.updated_at=incident.recovered_at=new Date().toISOString();
        incident.audit.push(`${incident.updated_at} Five healthy replay observations; recovered.`); save();
      }
    }
    value = {...frame, price_history:[], incidents:copy(journal), last_change:lastChange, assessment,
      observations:count, completed_investigations:completed, pending_investigations:0,
      explanation_latency_ms:null, mode:'BROWSER SIMULATION / PREPARED REPLAY',
      timeline:timeline.slice(0,12), broker_connected:false};
    listener?.(value);
  }
  window.SamFxDemo = {
    runbooks: fixtures.runbooks,
    start(callback) {
      listener=callback; begin('baseline'); tick(); setInterval(tick,1000);
      document.querySelector('a[href="#handover"]').addEventListener('click',event=>{
        event.preventDefault();
        const payload={mode:'Synthetic browser replay; not a production record', exported_at:new Date().toISOString(),
          incidents:journal,evidence_packages:evidence, pending_investigations:0,failed_investigations:0};
        const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
        const a=document.createElement('a'); a.href=url; a.download='sam-fx-handover.json'; a.click();
        setTimeout(()=>URL.revokeObjectURL(url),1000);
      });
    },
    get storageAvailable() { return storageAvailable; },
    async post(path) {
      if(path.startsWith('/api/scenarios/')) {
        const name=path.split('/').pop(); baselineClip=['market','infrastructure','feed_loss','telemetry_loss','capacity'].includes(name)?'legacy_baseline':'baseline'; if(!fixtures.clips[name]) throw new Error('Unknown scenario');
        for(const item of journal) {
          if(item.runbook==='aiops' && ['OPEN','ACKNOWLEDGED'].includes(item.status)) {
            item.status='RESOLVED'; item.updated_at=new Date().toISOString();
            item.audit.push(`${item.updated_at} Demo scenario replaced; not a measured recovery.`);
          }
        }
        save(); lastChange=null; assessment=null; begin(name); tick(); return value;
      }
      if(path==='/api/recover') { begin('baseline'); value.running=false; value.scenario='baseline'; listener(value); return value; }
      const match=path.match(/^\/api\/incidents\/([^/]+)\/(acknowledge|resolve)$/);
      if(!match) throw new Error('Unsupported action');
      const incident=journal.find(i=>i.incident_id===match[1]);
      if(!incident) throw new Error('Incident not found');
      if(match[2]==='acknowledge' && incident.status==='OPEN') incident.status='ACKNOWLEDGED';
      else if(match[2]==='resolve' && incident.status==='RECOVERED') incident.status='RESOLVED';
      else throw new Error('Resolve only after confirmed recovery.');
      incident.updated_at=new Date().toISOString();
      incident.audit.push(`${incident.updated_at} Browser demo operator: ${match[2]}.`);
      save(); value.incidents=copy(journal); listener(value); return copy(incident);
    }
  };
})();
