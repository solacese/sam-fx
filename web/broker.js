/* Read-only view of scoped normalized CLI fixtures and frozen cross-source findings. */
'use strict';
(() => {
  const el=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const names={ALIGNED:'Within reference',CONSUMER_BACKPRESSURE:'Consumer not reading',NETWORK_DEGRADATION:'NYC network degradation',ACK_STALL:'Consumer ACK / processing stall',SOURCE_DIVERGENCE:'Tokyo source divergence',REFERENCE_UNAVAILABLE:'Reference unavailable',UNDETERMINED:'Cause not established'};
  function rows(items){return `<dl class="feed-metrics">${items.map(([k,v,w])=>`<div><dt>${esc(k)}</dt><dd class="${w?'metric-warn':''}">${esc(v)}</dd></div>`).join('')}</dl>`;}
  window.SamFxBroker={render(s,a){
    const state=s.aiops,cli=state?.broker_cli;if(!cli)return;
    const sources=Object.fromEntries(state.sources.map(x=>[x.evidence_id,x.metrics]));
    const t=sources.broker_tcp,q=sources.broker_queue,c=sources.corvil_tcp;
    const available=cli.captures.every(x=>x.status==='SIMULATED'||x.status==='OK');
    const open=el('broker-feed').querySelector('details')?.open;
    el('broker-feed').innerHTML=available?rows([
      ['Transmit window',t.transmit_window_bytes.toLocaleString('en-GB')+' B',t.transmit_window_bytes===0],
      ['Delivered-unacked',q.unacked_messages+' / '+q.max_delivered_unacked_per_flow,q.unacked_limit_headroom===0],
      ['Queue depth',q.queue_depth.toLocaleString('en-GB')+' msgs',q.queue_depth>100],
    ])+`<details${open?' open':''}><summary>More metrics</summary>${rows([
      ['Blocked · last ~60s',t.blocked_pct.toFixed(1)+'%',t.blocked_pct>5],['TCP send buffer',t.send_queue_bytes+' B'],
      ['Broker client queue',t.client_egress_queue_bytes+' B'],['Fast / timed RTX Δ',t.fast_retransmit_delta+' / '+t.timed_retransmit_delta],
      ['SRTT / variation',t.srtt_us+' / '+t.rttvar_us+' µs'],['Congestion window',t.congestion_window_bytes+' B'],
      ['Flow / state',q.flow_id+' · '+q.flow_state],['Unacked headroom',q.unacked_limit_headroom],
      ['Ingress → egress',q.ingress_rate+' → '+q.egress_rate+'/s'],['Oldest · sim metadata',q.oldest_message_ms+' ms'],
      ['Redelivered / expired Δ',q.redelivered_delta+' / '+q.expired_delta],
    ])}</details>`:'<p class="stale">CLI unavailable · cause unconfirmed</p>';
    el('cli-captures').innerHTML=`<p class="frozen-note">${esc(cli.broker)} · ${esc(cli.vpn)} · flow ${cli.flow_id}<br>${esc(cli.connection_epoch)} · ${esc(cli.ad_role)}<br>SIMULATED normalized fields · not a broker session</p>${cli.captures.map(x=>`<div class="cli-capture"><small>${esc(x.status)} · ${esc(new Date(x.sampled_at).toISOString())}</small><code>${esc(x.command)}</code><pre>${esc(JSON.stringify(x.values,null,2))}</pre></div>`).join('')}`;
    const corvilOpen=el('corvil-feed').querySelector('details')?.open;
    el('corvil-feed').innerHTML=rows([
      ['NYC session RTT',c.rtt_ms.toFixed(1)+' ms',c.rtt_ms>5],['Retransmissions',c.retransmit_pct.toFixed(2)+'%',c.retransmit_pct>.5],
      ['Peer receive window',c.peer_receive_window_bytes.toLocaleString('en-GB')+' B',c.peer_receive_window_bytes===0],
    ])+`<details${corvilOpen?' open':''}><summary>More metrics</summary>${rows([
      ['Peer RTT',c.peer_rtt_ms+' ms'],['Source → broker p99',c.source_to_broker_p99_ms+' ms'],
      ['Broker → NYC p99',c.broker_to_consumer_p99_ms+' ms'],['Zero-window probes Δ',c.zero_window_probes_delta],
      ['Capture drops',c.capture_drops],['Clock uncertainty',c.capture_clock_uncertainty_us+' µs'],
    ])}</details>`;
    const diagnosis=a?.diagnosis_at_event||(!a?state.diagnosis:null);
    el('diagnosis-evidence').innerHTML=diagnosis?`<div class="diagnosis-label"><strong>${esc(names[diagnosis.hypothesis]||diagnosis.hypothesis)}</strong><small>${a?'Frozen evidence':'Current observations'} · working hypothesis</small></div><div class="triangulation">${diagnosis.evidence.map(e=>`<div><span class="label">${e.source==='BROKER_CLI'?'BROKER CLI':esc(e.source)}</span><p>${esc(e.finding)}</p></div>`).join('')}</div><small class="frozen-note">Price verdict is independent of technical diagnosis. CLI and Corvil may observe the same TCP symptom.</small>`:'';
  }};
})();
