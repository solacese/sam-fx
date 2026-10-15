/* Candles aggregate timestamped simulated mid-prices. Missing ticks are not filled. */
'use strict';
(() => {
  const el = id => document.getElementById(id), svg = el('chart');
  const utc = value => new Date(value).toLocaleTimeString('en-GB', {timeZone:'UTC'});
  let points = [], seconds = 300, interval = 5, showAverage = true;
  let received = 0, connected = false, geometry = null, inspection = null;
  const left = 8, top = 15;
  let right = 818, bottom = 310;
  svg.setAttribute('tabindex', '0');
  svg.setAttribute('aria-label', 'Simulated EUR/USD candlestick chart. Use left and right arrow keys to inspect candles.');
  function candlesFor(source) {
    const buckets = new Map();
    for(const p of source) {
      const t = Math.floor(p.t/(interval*1000))*interval*1000;
      let c = buckets.get(t);
      if(!c) { c={t,open:p.mid,high:p.mid,low:p.mid,close:p.mid,count:0,last:p}; buckets.set(t,c); }
      c.high=Math.max(c.high,p.mid); c.low=Math.min(c.low,p.mid); c.close=p.mid; c.count++; c.last=p;
    }
    return [...buckets.values()];
  }
  function draw() {
    if(!points.length) return;
    const width = Math.max(320,svg.clientWidth), height = width < 540 ? 290 : 340;
    right=width-69; bottom=height-32; svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    const latest=points.at(-1), end=(Math.floor(latest.t/(interval*1000))+1)*interval*1000;
    const start=end-seconds*1000, visible=points.filter(p=>p.t>=start), candles=candlesFor(visible);
    if(!candles.length) return;
    const low=Math.min(...visible.map(p=>p.mid)), high=Math.max(...visible.map(p=>p.mid));
    const pad=Math.max((high-low)*.12,.000025), lo=low-pad, hi=high+pad;
    const x=t=>left+(t-start)/(end-start)*(right-left), y=v=>bottom-(v-lo)/(hi-lo)*(bottom-top);
    const center=c=>x(c.t+interval*500);
    const bodyWidth=Math.max(1,Math.min(10,(right-left)/(seconds/interval)*.62));
    let grid=`<rect x="${right}" y="0" width="69" height="${height}" fill="#edf1f6"/><line class="axis" x1="${right}" x2="${right}" y1="0" y2="${bottom}"/>`;
    for(let i=0;i<=6;i++) {
      const yy=top+(bottom-top)*i/6, v=hi-(hi-lo)*i/6;
      grid+=`<line x1="${left}" x2="${right}" y1="${yy}" y2="${yy}"/><text x="${right+5}" y="${yy+4}">${v.toFixed(5)}</text>`;
    }
    const ticks=width<540?2:6;
    for(let i=0;i<=ticks;i++) {
      const t=start+(end-start)*i/ticks, xx=x(t);
      grid+=`<line x1="${xx}" x2="${xx}" y1="${top}" y2="${bottom}"/><text class="time-tick" x="${xx}" y="${bottom+22}" text-anchor="${i===0?'start':i===ticks?'end':'middle'}">${utc(t)}</text>`;
    }
    el('chart-grid').innerHTML=grid;
    el('chart-candles').innerHTML=candles.map(c=>{
      const xx=center(c), yy=Math.min(y(c.open),y(c.close)), hh=Math.max(1,Math.abs(y(c.open)-y(c.close)));
      return `<g class="candle ${c.close>=c.open?'up':'down'}"><line x1="${xx}" x2="${xx}" y1="${y(c.high)}" y2="${y(c.low)}"/><rect x="${xx-bodyWidth/2}" y="${yy}" width="${bodyWidth}" height="${hh}"/></g>`;
    }).join('');
    // The ten-candle average restarts after a missing bucket or missing source observation.
    const all=candlesFor(points), averages=[]; let run=[];
    for(const c of all) {
      if(run.length && (c.t-run.at(-1).t>interval*1000 || run.at(-1).count<interval)) run=[];
      run.push(c); run=run.slice(-10);
      if(c.t>=start && run.length===10) averages.push({t:c.t+interval*500,value:run.reduce((s,p)=>s+p.close,0)/10});
    }
    const averagePath=averages.map((p,i)=>`${i&&p.t-averages[i-1].t<=interval*1000?'L':'M'}${x(p.t)},${y(p.value)}`).join(' ');
    el('price-path').setAttribute('d',showAverage?averagePath:'');
    el('chart-average-key').textContent=showAverage?(averages.length?'━ SMA 10':'SMA 10 · collecting'):'SMA 10 off';
    const yy=y(latest.mid);
    el('chart-last').innerHTML=`<line x1="${left}" x2="${right}" y1="${yy}" y2="${yy}" stroke="#719ac9" stroke-dasharray="2 4"/><rect x="${right}" y="${yy-9}" width="68" height="18" fill="#e6effb" stroke="#2d78d3"/><text x="${right+4}" y="${yy+4}">${latest.mid.toFixed(5)}</text>`;
    geometry={candles,x:center,y};
    const change=(latest.mid-visible[0].mid)*10000;
    el('price-change').textContent=`${change>=0?'+':''}${change.toFixed(1)} pips · observed window`;
    el('price-change').className=change>0?'positive':change<0?'negative':'';
    el('chart-range').textContent=`${utc(visible[0].t)} – ${utc(latest.t)} UTC · ${((high-low)*10000).toFixed(1)} pip range`;
    el('window-range').textContent=`${interval}-second candles · ${candles.length} bars · last bar forming`;
    el('chart-coverage').textContent=`${visible.length} source observations · simulated`;
    el('chart-description').textContent=`Simulated EUR/USD, ${interval}-second OHLC candles from ${visible.length} observed prices. Low ${low.toFixed(5)}, high ${high.toFixed(5)}, latest ${latest.mid.toFixed(5)}. Hollow candles rise, filled candles fall. Last candle is forming.`;
    // Overview uses only collected history, with the selected trailing window highlighted.
    const overview=el('chart-overview'), first=points[0].t, span=Math.max(300000,latest.t-first);
    const ox=t=>4+(t-(latest.t-span))/span*992, oy=v=>35-(v-Math.min(...points.map(p=>p.mid)))/Math.max(.000001,Math.max(...points.map(p=>p.mid))-Math.min(...points.map(p=>p.mid)))*28;
    const overviewPath=points.map((p,i)=>`${i?'L':'M'}${ox(p.t)},${oy(p.mid)}`).join(' ');
    overview.innerHTML=`<path d="${overviewPath} L${ox(latest.t)},40 L${ox(first)},40 Z" fill="#ccd7e5"/><path d="${overviewPath}" fill="none" stroke="#94a9c3"/><rect x="${4+(1-seconds*1000/span)*992}" y="1" width="${seconds*1000/span*992}" height="38" fill="#3576ca0d" stroke="#365d8d"/>`;
    if(inspection!==null) inspect(inspection);
  }
  function status() {
    const stale=received&&(!connected||Date.now()-received>3500);
    el('chart-status').textContent=!received?'Waiting for prices':stale?'Stream paused · last price held':'● Updating · simulated';
    el('chart-status').className=stale?'stale':'';
  }
  function inspect(index) {
    if(!geometry) return;
    const {candles,x,y}=geometry;
    inspection=Math.max(0,Math.min(index,candles.length-1));
    const c=candles[inspection], xx=x(c), yy=y(c.close);
    el('chart-crosshair').innerHTML=`<line x1="${xx}" x2="${xx}" y1="${top}" y2="${bottom}" stroke="#71839b" stroke-dasharray="3 3"/><line x1="${left}" x2="${right}" y1="${yy}" y2="${yy}" stroke="#71839b" stroke-dasharray="3 3"/>`;
    el('chart-crosshair').removeAttribute('hidden'); el('chart-tooltip').hidden=false;
    el('chart-tooltip').textContent=`${utc(c.t)} UTC · ${interval}s${inspection===candles.length-1?' · forming':''}\nO ${c.open.toFixed(5)}  H ${c.high.toFixed(5)}\nL ${c.low.toFixed(5)}  C ${c.close.toFixed(5)}\n${c.count} observations · BID ${c.last.bid.toFixed(5)} / ASK ${c.last.ask.toFixed(5)}`;
  }
  function clearInspection(){inspection=null;el('chart-crosshair').setAttribute('hidden','');el('chart-tooltip').hidden=true;}
  svg.addEventListener('pointermove',event=>{
    if(!geometry) return;
    const pt=svg.createSVGPoint();pt.x=event.clientX;pt.y=event.clientY;
    const xx=pt.matrixTransform(svg.getScreenCTM().inverse()).x;
    inspect(geometry.candles.reduce((best,c,i)=>Math.abs(geometry.x(c)-xx)<Math.abs(geometry.x(geometry.candles[best])-xx)?i:best,0));
  });
  svg.addEventListener('pointerleave',clearInspection);svg.addEventListener('blur',clearInspection);
  svg.addEventListener('keydown',event=>{
    if(!geometry||!['ArrowLeft','ArrowRight','Escape'].includes(event.key))return;
    event.preventDefault();if(event.key==='Escape')return clearInspection();
    inspect((inspection??geometry.candles.length-1)+(event.key==='ArrowLeft'?-1:1));
  });
  document.querySelectorAll('[data-window]').forEach(button=>button.addEventListener('click',()=>{
    seconds=Number(button.dataset.window);clearInspection();
    document.querySelectorAll('[data-window]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));draw();
  }));
  document.querySelectorAll('[data-interval]').forEach(button=>button.addEventListener('click',()=>{
    interval=Number(button.dataset.interval);clearInspection();
    document.querySelectorAll('[data-interval]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));draw();
  }));
  el('chart-average').addEventListener('click',()=>{showAverage=!showAverage;el('chart-average').setAttribute('aria-pressed',String(showAverage));draw();});
  window.SamFxChart={
    update(snapshot,history=[]){
      const merged=new Map(points.map(p=>[p.t,p]));
      for(const p of [...history,snapshot].filter(Boolean)){
        const t=Date.parse(p.timestamp);
        if(Number.isFinite(t)&&[p.mid,p.bid,p.ask].every(Number.isFinite))merged.set(t,{t,mid:p.mid,bid:p.bid,ask:p.ask});
      }
      const sorted=[...merged.values()].sort((a,b)=>a.t-b.t);if(!sorted.length)return;
      if(!points.length||sorted.at(-1).t>points.at(-1).t)received=Date.now();
      points=sorted.filter(p=>p.t>=sorted.at(-1).t-300000).slice(-301);connected=true;draw();status();
    },
    disconnect(){connected=false;status();}
  };
  new ResizeObserver(draw).observe(svg);setInterval(status,1000);
})();
