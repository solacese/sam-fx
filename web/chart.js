/* Timestamped source prices; no invented history or interpolated market data. */
'use strict';
(() => {
  const el = id => document.getElementById(id);
  const svg = el('chart');
  const utc = value => new Date(value).toLocaleTimeString('en-GB', {timeZone:'UTC'});
  let points = [], seconds = 300, received = 0, connected = false, geometry = null, inspection = null;
  const left = 12, top = 16;
  let right = 818, bottom = 250;
  svg.setAttribute('tabindex', '0');
  svg.setAttribute('aria-label', 'Simulated EUR/USD price chart. Use left and right arrow keys to inspect observations.');
  function draw() {
    if(!points.length) return;
    const width = Math.max(340, svg.clientWidth), height = width < 540 ? 260 : 290;
    right = width - 80; bottom = height - 40;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const end = points.at(-1).t, start = end - seconds * 1000;
    const visible = points.filter(p => p.t >= start);
    const values = visible.map(p => p.mid);
    const low = Math.min(...values), high = Math.max(...values);
    const pad = Math.max((high-low)*.18, .00003), lo = low-pad, hi = high+pad;
    const x = t => left + (t-start)/(end-start)*(right-left);
    const y = v => bottom - (v-lo)/(hi-lo)*(bottom-top);
    geometry = {visible,x,y};
    let grid = '';
    for(let i=0;i<=4;i++) {
      const yy = top+(bottom-top)*i/4, v = hi-(hi-lo)*i/4;
      grid += `<line x1="${left}" x2="${right}" y1="${yy}" y2="${yy}"/><text x="${right+9}" y="${yy+4}">${v.toFixed(5)}</text>`;
      const xx = left+(right-left)*i/4;
      grid += `<line x1="${xx}" x2="${xx}" y1="${top}" y2="${bottom}"/>`;
      if(width >= 540 || i % 2 === 0) grid += `<text x="${xx}" y="${bottom+28}" text-anchor="${i===0?'start':i===4?'end':'middle'}">${utc(start+(end-start)*i/4)}</text>`;
    }
    el('chart-grid').innerHTML = grid;
    const segments = [];
    for(const p of visible) {
      if(!segments.length || p.t-segments.at(-1).at(-1).t>3500) segments.push([]);
      segments.at(-1).push(p);
    }
    const paths = segments.map(segment => segment.map((p,i)=>`${i?'L':'M'}${x(p.t).toFixed(2)},${y(p.mid).toFixed(2)}`).join(' '));
    el('price-path').setAttribute('d',paths.join(' '));
    el('price-area').setAttribute('d',segments.map((segment,i)=>`${paths[i]} L${x(segment.at(-1).t)},${bottom} L${x(segment[0].t)},${bottom} Z`).join(' '));
    const last = visible.at(-1), yy = y(last.mid);
    el('chart-last').innerHTML = `<line x1="${x(last.t)}" x2="${right}" y1="${yy}" y2="${yy}" stroke="#00dcaa" stroke-dasharray="3 4"/><circle cx="${x(last.t)}" cy="${yy}" r="3.5" fill="#00dcaa"/><rect x="${right+4}" y="${yy-10}" width="72" height="20" fill="#00dcaa"/><text x="${right+40}" y="${yy+4}" text-anchor="middle">${last.mid.toFixed(5)}</text>`;
    const change = (last.mid-visible[0].mid)*10000;
    el('price-change').textContent = `${change>=0?'+':''}${change.toFixed(1)} pips · observed window`;
    el('price-change').className = change>0?'positive':change<0?'negative':'';
    el('window-range').textContent = `LOW ${low.toFixed(5)} / HIGH ${high.toFixed(5)}`;
    el('chart-coverage').textContent = `${visible.length} observations · ${Math.round((end-visible[0].t)/1000)}s collected / ${seconds/60}m window`;
    el('chart-description').textContent = `Simulated EUR/USD. ${visible.length} observations. Low ${low.toFixed(5)}, high ${high.toFixed(5)}, latest ${last.mid.toFixed(5)}. Gaps mean missing observations.`;
    if(inspection !== null) inspect(inspection);
  }
  function status() {
    const stale = received && (!connected || Date.now()-received>3500);
    el('chart-status').textContent = !received ? 'Waiting for prices' : stale ? 'Stream paused · last price held' : 'Updating every second · demo';
    el('chart-status').className = stale ? 'stale' : '';
  }
  function inspect(index) {
    if(!geometry) return;
    const {visible,x,y} = geometry;
    inspection = Math.max(0,Math.min(index,visible.length-1));
    const p = visible[inspection];
    el('chart-crosshair').innerHTML = `<line x1="${x(p.t)}" x2="${x(p.t)}" y1="${top}" y2="${bottom}" stroke="#91aaaf" stroke-dasharray="3 4"/><circle cx="${x(p.t)}" cy="${y(p.mid)}" r="4" fill="#091417" stroke="#e0ebec"/>`;
    el('chart-crosshair').removeAttribute('hidden');
    el('chart-tooltip').hidden = false;
    el('chart-tooltip').textContent = `${utc(p.t)} UTC · MID ${p.mid.toFixed(5)}\nBID ${p.bid.toFixed(5)} / ASK ${p.ask.toFixed(5)}`;
  }
  function clearInspection() { inspection=null; el('chart-crosshair').setAttribute('hidden',''); el('chart-tooltip').hidden=true; }
  svg.addEventListener('pointermove', event => {
    if(!geometry) return;
    const pt=svg.createSVGPoint(); pt.x=event.clientX; pt.y=event.clientY;
    const xx=pt.matrixTransform(svg.getScreenCTM().inverse()).x;
    const index=geometry.visible.reduce((best,p,i)=>Math.abs(geometry.x(p.t)-xx)<Math.abs(geometry.x(geometry.visible[best].t)-xx)?i:best,0);
    inspect(index);
  });
  svg.addEventListener('pointerleave',clearInspection);
  svg.addEventListener('blur',clearInspection);
  svg.addEventListener('keydown', event => {
    if(!geometry || !['ArrowLeft','ArrowRight','Escape'].includes(event.key)) return;
    event.preventDefault();
    if(event.key==='Escape') return clearInspection();
    inspect((inspection ?? geometry.visible.length-1)+(event.key==='ArrowLeft'?-1:1));
  });
  document.querySelectorAll('[data-window]').forEach(button => button.addEventListener('click',()=>{
    seconds=Number(button.dataset.window); clearInspection();
    document.querySelectorAll('[data-window]').forEach(b=>b.setAttribute('aria-pressed',String(b===button))); draw();
  }));
  window.SamFxChart = {
    update(snapshot, history=[]) {
      const incoming=[...history,snapshot].filter(Boolean);
      const merged=new Map(points.map(p=>[p.t,p]));
      for(const p of incoming) {
        const t=Date.parse(p.timestamp);
        if(Number.isFinite(t) && [p.mid,p.bid,p.ask].every(Number.isFinite)) merged.set(t,{t,mid:p.mid,bid:p.bid,ask:p.ask});
      }
      const sorted=[...merged.values()].sort((a,b)=>a.t-b.t);
      if(!sorted.length) return;
      if(!points.length || sorted.at(-1).t>points.at(-1).t) received=Date.now();
      points=sorted.filter(p=>p.t>=sorted.at(-1).t-300000).slice(-301);
      connected=true; draw(); status();
    },
    disconnect() { connected=false; status(); }
  };
  new ResizeObserver(draw).observe(svg);
  setInterval(status,1000);
})();
