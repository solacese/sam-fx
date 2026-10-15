/* Live source boxes and an evidence-bound investigation graph. */
'use strict';
(() => {
  const el=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const rows=items=>`<dl class="feed-metrics">${items.map(([label,value,tone])=>`<div><dt>${esc(label)}</dt><dd class="${tone||''}">${esc(value)}</dd></div>`).join('')}</dl>`;
  const n=(v,d=0)=>typeof v==='number'?v.toLocaleString('en-GB',{minimumFractionDigits:d,maximumFractionDigits:d}):String(v??'—');
  const warning=v=>Number(v)>0?'metric-warn':'';
  const labels={WITHIN_LIMITS:'WITHIN LIMITS',WATCH:'WATCH',AT_RISK:'AT RISK',IMPAIRED:'IMPAIRED',UNKNOWN:'UNKNOWN'};
  function graph(a,incident){
    if(!a?.graph){
      el('graph-mode').textContent='Awaiting investigation';
      el('explanation-graph').innerHTML='<p>The investigator will join Tokyo market activity, NYC connection pressure, queue depth and price freshness here.</p>';
      return;
    }
    el('graph-mode').textContent=`Frozen evidence · ${a.model.includes('fallback')?'prepared':'LLM investigation'}`;
    const xy={tokyo_source:[12,14],nyc_tcp:[360,14],nyc_queue:[360,160],data_quality:[12,160]};
    const paths={market_tcp_sequence:'M302 58 H360',market_tcp:'M302 58 H360',tcp_queue:'M505 102 V160',queue_data:'M360 204 H302',tcp_data:'M360 70 C320 70 340 180 302 192'};
    const labelXY={market_tcp_sequence:[331,45],market_tcp:[331,45],tcp_queue:[505,133],queue_data:[331,190],tcp_data:[330,142]};
    const arrows=a.graph.edges.map(e=>{const p=labelXY[e.edge_id];return `<g><path d="${paths[e.edge_id]||''}" class="graph-link ${e.kind==='sequence'?'graph-sequence':''}" marker-end="url(#graph-arrow)"/><text x="${p?.[0]||0}" y="${p?.[1]||0}" class="graph-edge-label" text-anchor="middle">${e.kind==='sequence'?'then':e.edge_id==='market_tcp'?'load?':e.edge_id==='tcp_queue'?'backpressure?':'delay?'}</text><title>${esc(e.label)} · ${esc(e.kind)} · ${esc(e.evidence_ids.join(', '))}</title></g>`;}).join('');
    const nodes=a.graph.nodes.map(node=>{const [x,y]=xy[node.node_id]||[12,14];return `<g transform="translate(${x},${y})"><rect width="290" height="88" rx="2" class="graph-node ${node.node_id===a.suspected_component?'suspect-node':''}"/><text x="12" y="20" class="graph-region">${esc(node.region)}${node.change_offset_s==null?'':' · t+'+node.change_offset_s+'s'}</text><text x="12" y="42" class="graph-title">${esc(node.label)}</text><text x="12" y="65" class="graph-detail">${esc(node.detail)}</text><title>${esc(node.evidence_ids.join(', '))}</title></g>`;}).join('');
    el('explanation-graph').innerHTML=`<svg viewBox="0 0 664 264" role="img" aria-label="Investigation hypothesis graph: ${esc(a.graph.nodes.map(n=>n.label+': '+n.detail).join('; '))}"><defs><marker id="graph-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="#e5b763"/></marker></defs>${arrows}${nodes}</svg><div class="graph-caption">Evidence ${esc(a.correlation_id.slice(0,8))} · ${esc(new Date(incident?.opened_at||a.timestamp).toLocaleTimeString('en-GB',{timeZone:'UTC'}))} UTC · ${a.graph.edges.length?'Links are suspected, not proven.':'No supported causal chain selected.'}</div>`;
  }
  window.SamFxAiops={render(s,a,incident){
    const data=s.aiops;
    if(data){
      el('data-confidence').textContent=labels[data.status]||data.status;
      el('data-confidence').className=data.status.toLowerCase();
      el('confidence-detail').textContent=`${data.path_id} · technical score ${data.technical_score.toFixed(1)}/6 · ${data.confirmed?'confirmed':data.status==='WITHIN_LIMITS'?'observing':data.confirmation_count+'/3 confirming'}`;
      const source=Object.fromEntries(data.sources.map(e=>[e.evidence_id,e]));
      const m=source.market.metrics,c=source.corvil_tcp.metrics,t=source.semp_tcp.metrics,q=source.semp_queue.metrics,d=source.data_quality.metrics;
      el('market-feed').innerHTML=rows([
        ['EUR/USD mid',s.snapshot?.mid.toFixed(5)],['Quotes / second',n(m.quote_rate),m.quote_rate>50?'metric-warn':''],
        ['Spread',n(m.spread_pips,1)+' pips'],['Source quote age',n(m.source_quote_age_ms)+' ms'],['Source gaps',n(m.source_sequence_gaps)],
      ]);
      el('corvil-feed').innerHTML=rows([
        ['NYC session RTT',n(c.rtt_ms,1)+' ms',c.rtt_ms>5?'metric-warn':''],
        ['Retransmissions',n(c.retransmit_pct,2)+'%',c.retransmit_pct>.5?'metric-warn':''],
        ['Path p99',n(c.path_p99_ms)+' ms'],['Peer RTT',n(c.peer_rtt_ms,1)+' ms'],
        ['Peer quote age',n(c.peer_quote_age_ms)+' ms'],['Capture drops',n(c.capture_drops)],
      ]);
      el('semp-feed').innerHTML=`<div class="connection-id">${esc(data.connection.client_id)}<br><span>${esc(data.connection.local)} →<br>${esc(data.connection.remote)}</span></div>`+rows([
        ['TCP state',t.tcp_state],['SRTT',n(t.srtt_us)+' µs'],['RTT variation',n(t.rttvar_us)+' µs'],
        ['Fast / timed RTX',n(t.fast_retransmit_delta)+' / '+n(t.timed_retransmit_delta),warning(t.fast_retransmit_delta)],
        ['Blocked',n(t.blocked_pct)+'%',warning(t.blocked_pct)],['Send buffer',n(t.send_queue_bytes)+' B',t.send_queue_bytes>10000?'metric-warn':''],
        ['Receive buffer',n(t.receive_queue_bytes)+' B'],['Advertised window',n(t.advertised_window_bytes)+' B'],
        ['Transmit window',n(t.transmit_window_bytes)+' B',t.transmit_window_bytes===0?'metric-warn':''],
        ['Congestion window',n(t.congestion_window_bytes)+' B'],['Queue depth',n(q.queue_depth)+' msgs',q.queue_depth>100?'metric-warn':''],
        ['Oldest message',n(q.oldest_message_ms)+' ms'],['Unacknowledged',n(q.unacked_messages)],
        ['Ingress → egress',n(q.ingress_rate)+' → '+n(q.egress_rate)+'/s'],
      ]);
      for(const [prefix,item] of [['market',source.market],['corvil',source.corvil_tcp],['semp',source.semp_tcp]]){
        const age=Math.max(0,(Date.parse(data.timestamp)-Date.parse(item.timestamp))/1000);
        el(prefix+'-feed-age').textContent=`SIMULATED · ${age>3?'STALE '+age+'s':new Date(item.timestamp).toLocaleTimeString('en-GB',{timeZone:'UTC'})+' UTC'}`;
        el(prefix+'-feed-age').className='feed-foot '+(age>3?'stale':'');
      }
      el('greg-brief').innerHTML=`<div class="brief-top"><span class="label">${a?'CONFIDENCE AT EVENT':'CAN I TRUST THIS FX DATA?'}</span><span class="pill ${(a?.confidence_at_event||data.status).toLowerCase()}">${esc(labels[a?.confidence_at_event||data.status])}</span></div><p>${esc(a?.assessment||(s.pending_investigations?'Investigation running. Reading the frozen Market, Corvil and SEMP v1 evidence…':data.status==='WITHIN_LIMITS'?'Observed quality is within the demo limits. Market activity alone does not make the feed untrustworthy.':'Waiting for three abnormal observations before investigation.'))}</p>${a?`<div class="brief-next"><span class="label">NEXT CHECK</span><p>${esc(a.suggested_next_investigation)}</p></div>`:''}<div class="brief-meta">${a?esc(a.model.includes('fallback')?'Prepared fallback · no successful LLM result':a.model+' · '+(a.latency_ms/1000).toFixed(2)+'s investigation'):s.llm_enabled?'Live LLM ready · bounded investigation':'Prepared replay · LLM disabled'}</div>${a?.suspected_component?`<div class="suspect-line">Suspect: <strong>${esc(a.suspected_component.replaceAll('_',' '))}</strong><small>${esc(data.connection.local)} → ${esc(data.connection.remote)}</small></div>`:''}${a?.checks?.length?`<details><summary>${a.checks.length} source checks · simulated reads</summary><ul class="check-list">${a.checks.map(c=>`<li><span>✓ ${esc(c.source)}</span> ${esc(c.name)}</li>`).join('')}</ul></details>`:''}<div class="freshness-line">Current NYC quote age <strong class="${d.quote_age_ms>=1000?'metric-warn':''}">${n(d.quote_age_ms)} ms</strong> / 1,000 ms demo budget</div>${a?'<small class="frozen-note">Explanation is frozen at the event; feed boxes remain live.</small>':''}`;
    }
    graph(a,incident);
  }};
})();
