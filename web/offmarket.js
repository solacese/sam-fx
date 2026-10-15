/* The numeric comparator owns the verdict; the model only investigates its evidence. */
'use strict';
(() => {
  const el=id=>document.getElementById(id);
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const price=v=>Number.isFinite(v)?v.toFixed(5):'—';
  const pips=v=>Number.isFinite(v)?(v>=0?'+':'')+v.toFixed(1):'—';
  const names={WITHIN_BAND:'WITHIN REFERENCE',SUSPECTED:'CONFIRMING',OFF_MARKET:'OFF-MARKET',UNKNOWN:'REFERENCE UNKNOWN'};
  const history=[];
  function curve(c){
    if(history.at(-1)?.timestamp!==c.timestamp){history.push(c);if(history.length>60)history.shift();}
    const points=history.flatMap(p=>[p.delivered_mid,p.reference_mid]).filter(Number.isFinite);
    const lo=Math.min(...points)-.00004,hi=Math.max(...points)+.00004;
    const x=i=>12+i/Math.max(1,history.length-1)*770,y=v=>92-(v-lo)/(hi-lo)*78;
    const path=key=>history.map((p,i)=>Number.isFinite(p[key])?`${i&&Number.isFinite(history[i-1][key])?'L':'M'}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`:'').join(' ');
    el('comparison-curve').innerHTML=`<line x1="12" x2="782" y1="92" y2="92" stroke="#294046"/><path d="${path('reference_mid')}" fill="none" stroke="#00dcaa" stroke-width="1.6"/><path d="${path('delivered_mid')}" fill="none" stroke="#e7ba6c" stroke-width="1.6" stroke-dasharray="4 2"/><text x="792" y="20">${hi.toFixed(5)}</text><text x="792" y="92">${lo.toFixed(5)}</text>`;
  }
  window.SamFxOffmarket={render(s,a){
    const c=s.aiops?.offmarket;
    el('comparison-curve').hidden=!c;
    if(!c){el('quote-comparison').innerHTML='<p>Historical incident selected. Run an off-market scenario to compare delivered and reference prices.</p>';el('reference-quality').textContent='No comparable reference package in this legacy scenario.';return;}
    el('data-confidence').textContent=names[c.status];el('data-confidence').className=c.status.toLowerCase();
    el('confidence-detail').textContent=c.status==='SUSPECTED'?`${c.consecutive}/3 confirming observations`:c.status==='OFF_MARKET'?`${c.consecutive} consecutive discrepancies`:c.status==='UNKNOWN'?'Withholding price verdict':c.confirmed?'Quotes aligned':'Checking alignment';
    el('quote-comparison').innerHTML=`<div><span class="label">NYC DELIVERED MID</span><strong>${price(c.delivered_mid)}</strong><small>${price(c.delivered_bid)} / ${price(c.delivered_ask)} · ${Math.round(c.delivered_age_ms)} ms old</small></div><div><span class="label">REFERENCE MID</span><strong>${price(c.reference_mid)}</strong><small>${c.reference_mid===null?'No valid quorum':price(c.reference_bid)+' / '+price(c.reference_ask)+' · '+c.contributors_used.length+'/3 agree'}</small></div><div class="price-difference ${c.status==='OFF_MARKET'?'off_market':''}"><span class="label">MID DIFFERENCE</span><strong>${pips(c.mid_delta_pips)} <span>pips</span></strong><small>${c.outside_band_pips===null?'Price discrepancy unconfirmed':c.outside_band_pips.toFixed(1)+' pips beyond quote band · 1.0 pip limit'}</small></div>`;
    el('reference-quality').innerHTML=`<table><thead><tr><th>Contributor</th><th>Bid / ask</th><th>Source age</th><th>Reference check</th></tr></thead><tbody>${c.reference_quotes.map(q=>`<tr><td>${esc(q.contributor)}</td><td>${price(q.bid)} / ${price(q.ask)}</td><td>${Math.round(Date.parse(c.timestamp)-Date.parse(q.timestamp))} ms</td><td>${esc(c.excluded[q.contributor]||(c.contributors_used.includes(q.contributor)?'Included':'No quorum'))}</td></tr>`).join('')}</tbody></table>`;
    const market=s.aiops.sources.find(x=>x.evidence_id==='market').metrics;
    const open=el('market-feed').querySelector('details')?.open;
    el('market-feed').innerHTML=`<dl class="feed-metrics"><div><dt>Tokyo source</dt><dd>${price(c.source_mid)}</dd></div><div><dt>Reference quorum</dt><dd class="${c.reference_mid===null?'metric-warn':''}">${c.contributors_used.length} / 3</dd></div><div><dt>Quotes / second</dt><dd>${market.quote_rate}</dd></div></dl><details${open?' open':''}><summary>More metrics</summary><p>Indicative EUR/USD spot · source timestamp 45 ms old. References travel over separate simulated paths.</p></details>`;
    // A pending event must not keep an older incident's explanation selected.
    if(!a && s.pending_investigations) el('explanation-mode').textContent='Investigating price discrepancy';
    curve(c);
  }};
})();
