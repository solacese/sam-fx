/* Live source boxes and an evidence-bound investigation graph. */
'use strict';
(() => {
  const el=id=>document.getElementById(id);
  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const rows=items=>`<dl class="feed-metrics">${items.map(([label,value,tone])=>`<div><dt>${esc(label)}</dt><dd class="${tone||''}">${esc(value)}</dd></div>`).join('')}</dl>`;
  const n=(v,d=0)=>typeof v==='number'?v.toLocaleString('en-GB',{minimumFractionDigits:d,maximumFractionDigits:d}):String(v??'—');
  const warning=v=>Number(v)>0?'metric-warn':'';
  const extra=(id,items)=>`<details${el(id).querySelector('details')?.open?' open':''}><summary>More metrics</summary>${rows(items)}</details>`;
  const labels={WITHIN_LIMITS:'WITHIN LIMITS',WATCH:'WATCH',AT_RISK:'AT RISK',IMPAIRED:'IMPAIRED',UNKNOWN:'UNKNOWN',WITHIN_BAND:'WITHIN REFERENCE',SUSPECTED:'CONFIRMING',OFF_MARKET:'OFF-MARKET'};
  function graph(a,incident){
    if(!a?.graph){
      el('graph-mode').textContent='Awaiting investigation';
      el('explanation-graph').innerHTML='<p>The investigator will join Tokyo market activity, NYC connection pressure, queue depth and price freshness here.</p>';
      return;
    }
    el('graph-mode').textContent=`Frozen evidence · ${a.model.includes('fallback')?'prepared':'LLM investigation'}`;
    const comparison=Boolean(a.offmarket_at_event);
    const xy=comparison?{reference:[12,14],tokyo_source:[360,14],nyc_tcp:[708,14],nyc_queue:[708,160],data_quality:[360,160]}:{tokyo_source:[12,14],nyc_tcp:[360,14],nyc_queue:[360,160],data_quality:[12,160]};
    const paths=comparison?{reference_source:'M302 58 H360',reference_data:'M157 102 C157 204 280 204 360 204',source_data:'M505 102 V160',tcp_queue:'M853 102 V160',queue_data:'M708 204 H650'}:{market_tcp_sequence:'M302 58 H360',market_tcp:'M302 58 H360',tcp_queue:'M505 102 V160',queue_data:'M360 204 H302',tcp_data:'M360 70 C320 70 340 180 302 192'};
    const labelXY=comparison?{reference_source:[331,45],reference_data:[250,190],source_data:[505,133],tcp_queue:[853,133],queue_data:[679,190]}:{market_tcp_sequence:[331,45],market_tcp:[331,45],tcp_queue:[505,133],queue_data:[331,190],tcp_data:[330,142]};
    const arrows=a.graph.edges.map(e=>{const p=labelXY[e.edge_id];return `<g><path d="${paths[e.edge_id]||''}" class="graph-link ${e.kind!=='hypothesis'?'graph-sequence':''}" marker-end="url(#${e.kind==='hypothesis'?'graph-arrow':'graph-observed-arrow'})"/><text x="${p?.[0]||0}" y="${p?.[1]||0}" class="graph-edge-label" text-anchor="middle">${e.edge_id==='reference_source'?(Math.abs(a.offmarket_at_event.source_delta_pips)<.5?'aligned':'differs'):e.edge_id==='reference_data'?'compare':e.edge_id==='source_data'?'source?':e.kind==='sequence'?'then':e.edge_id==='market_tcp'?'load?':e.edge_id==='tcp_queue'?'backpressure?':'delay?'}</text><title>${esc(e.label)} · ${esc(e.kind)} · ${esc(e.evidence_ids.join(', '))}</title></g>`;}).join('');
    const nodes=a.graph.nodes.map(node=>{const [x,y]=xy[node.node_id]||[12,14];return `<g transform="translate(${x},${y})"><rect width="290" height="88" rx="2" class="graph-node ${node.node_id===({nyc_consumer:'nyc_tcp',nyc_network:'nyc_tcp',nyc_application:'nyc_queue'}[a.suspected_component]||a.suspected_component)?'suspect-node':''}"/><text x="12" y="20" class="graph-region">${esc(node.region)}${node.change_offset_s==null?'':' · t+'+node.change_offset_s+'s'}</text><text x="12" y="42" class="graph-title">${esc(node.label)}</text><text x="12" y="65" class="graph-detail">${esc(node.detail)}</text><title>${esc(node.evidence_ids.join(', '))}</title></g>`;}).join('');
    el('explanation-graph').innerHTML=`<svg viewBox="0 0 ${comparison?1012:664} 264" role="img" aria-label="Investigation hypothesis graph: ${esc(a.graph.nodes.map(n=>n.label+': '+n.detail).join('; '))}"><defs><marker id="graph-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="#e5b763"/></marker><marker id="graph-observed-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="#8ea6ad"/></marker></defs>${arrows}${nodes}</svg><div class="graph-caption">Evidence ${esc(a.correlation_id.slice(0,8))} · ${esc(new Date(incident?.opened_at||a.timestamp).toLocaleTimeString('en-GB',{timeZone:'UTC'}))} UTC · ${a.graph.edges.length?'Comparison is measured; causes remain hypotheses.':'No supported causal chain selected.'}</div>`;
  }
  window.SamFxAiops={render(s,a,incident){
    const data=s.aiops;
    const eventStatus=a?.offmarket_at_event?.status||s.aiops?.offmarket?.status||a?.confidence_at_event||s.aiops?.status;
    const checksOpen=el('greg-brief').querySelector('details')?.open;
    if(data){
      el('data-confidence').textContent=labels[data.status]||data.status;
      el('data-confidence').className=data.status.toLowerCase();
      el('confidence-detail').textContent=`${data.status==='WITHIN_LIMITS'?'Monitoring three feeds':data.confirmed?'Confirmed change':data.confirmation_count+'/3 observations'} · ${data.technical_score.toFixed(1)}/6 deviation`;
      const source=Object.fromEntries(data.sources.map(e=>[e.evidence_id,e]));
      const m=source.market.metrics,c=source.corvil_tcp.metrics,t=source.broker_tcp.metrics,q=source.broker_queue.metrics,d=source.data_quality.metrics;
      el('market-feed').innerHTML=rows([
        ['EUR/USD mid',s.snapshot?.mid.toFixed(5)],['Quotes / second',n(m.quote_rate),m.quote_rate>50?'metric-warn':''],
        ['Spread',n(m.spread_pips,1)+' pips'],
      ])+extra('market-feed',[
        ['Source quote age',n(m.source_quote_age_ms)+' ms'],['Source gaps',n(m.source_sequence_gaps)],
      ]);
      el('corvil-feed').innerHTML=rows([
        ['NYC session RTT',n(c.rtt_ms,1)+' ms',c.rtt_ms>5?'metric-warn':''],
        ['Retransmissions',n(c.retransmit_pct,2)+'%',c.retransmit_pct>.5?'metric-warn':''],
        ['Peer RTT',n(c.peer_rtt_ms,1)+' ms'],
      ])+extra('corvil-feed',[
        ['Path p99',n(c.path_p99_ms)+' ms'],['Peer quote age',n(c.peer_quote_age_ms)+' ms'],['Capture drops',n(c.capture_drops)],
      ]);
      el('broker-feed').innerHTML=rows([
        ['TCP blocked',n(t.blocked_pct)+'%',warning(t.blocked_pct)],
        ['Transmit window',n(t.transmit_window_bytes)+' B',t.transmit_window_bytes===0?'metric-warn':''],
        ['Queue depth',n(q.queue_depth)+' msgs',q.queue_depth>100?'metric-warn':''],
      ])+extra('broker-feed',[
        ['TCP state',t.tcp_state],['SRTT',n(t.srtt_us)+' µs'],['RTT variation',n(t.rttvar_us)+' µs'],
        ['Fast / timed RTX',n(t.fast_retransmit_delta)+' / '+n(t.timed_retransmit_delta),warning(t.fast_retransmit_delta)],
        ['Send buffer',n(t.send_queue_bytes)+' B',t.send_queue_bytes>10000?'metric-warn':''],
        ['Receive buffer',n(t.receive_queue_bytes)+' B'],['Advertised window',n(t.advertised_window_bytes)+' B'],
        ['Congestion window',n(t.congestion_window_bytes)+' B'],
        ['Oldest message',n(q.oldest_message_ms)+' ms'],['Unacknowledged',n(q.unacked_messages)],
        ['Ingress → egress',n(q.ingress_rate)+' → '+n(q.egress_rate)+'/s'],
      ]);
      for(const [prefix,item] of [['market',source.market],['corvil',source.corvil_tcp],['broker',source.broker_tcp]]){
        const age=Math.max(0,(Date.parse(data.timestamp)-Date.parse(item.timestamp))/1000);
        el(prefix+'-feed-age').textContent=`SIMULATED · ${age>3?'STALE '+age+'s':new Date(item.timestamp).toLocaleTimeString('en-GB',{timeZone:'UTC'})+' UTC'}`;
        el(prefix+'-feed-age').className='feed-foot '+(age>3?'stale':'');
      }
      el('greg-brief').innerHTML=`<div class="brief-top"><span class="label">${a?'AT THE EVENT':'CURRENT ASSESSMENT'}</span><span class="pill ${eventStatus.toLowerCase()}">${esc(labels[eventStatus])}</span></div><p>${esc(a?.assessment||(s.pending_investigations?'Investigation running. Reading the frozen Market, Corvil and broker CLI evidence…':data.status==='WITHIN_LIMITS'?data.offmarket?'Delivered quotes remain aligned with the reference. A market move or one rejected reference does not trigger an investigation.':'Observed quality is within the demo limits. Market activity alone does not make the feed untrustworthy.':data.offmarket?.status==='UNKNOWN'?'Reference quality is insufficient. Withholding the off-market verdict.':'Confirming the quote discrepancy before investigation.'))}</p>${a?`<div class="brief-next"><span class="label">NEXT CHECK</span><p>${esc(a.suggested_next_investigation)}</p></div>`:''}<div class="brief-meta">${a?esc(a.model.includes('fallback')?'Prepared fallback · no successful LLM result':'LLM investigation · '+(a.latency_ms/1000).toFixed(2)+'s'):s.llm_enabled?'Live LLM ready · bounded investigation':'Prepared replay · LLM disabled'}</div>${a?.suspected_component?`<div class="suspect-line">Suspect: <strong>${esc(({nyc_consumer:'NYC consumer socket',nyc_network:'NYC network path',nyc_application:'NYC consumer ACK / processing',nyc_tcp:'NYC TCP connection',nyc_queue:'NYC Guaranteed queue',tokyo_source:'Tokyo source',reference:'Reference quality',unknown:'Undetermined'})[a.suspected_component]||a.suspected_component)}</strong></div>`:''}${a?.checks?.length?`<details${checksOpen?' open':''}><summary>${a.checks.length} source checks</summary><div class="connection-id">${esc(data.connection.client_id)}<br>${esc(data.connection.local)} → ${esc(data.connection.remote)}</div><ul class="check-list">${a.checks.map(c=>`<li><span>✓ ${esc(c.source)}</span> ${esc(c.name)}</li>`).join('')}</ul></details>`:''}<div class="freshness-line">NYC quote age <strong class="${d.quote_age_ms>=1000?'metric-warn':''}">${n(d.quote_age_ms)} ms</strong> <span> / 1,000 ms demo limit</span></div>${a?'<small class="frozen-note">Event snapshot · feeds on the left keep updating.</small>':''}`;
    }
    graph(a,incident);
  }};
})();
