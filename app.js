'use strict';
(() => {
  const data=window.SNAPSHOT;
  const $=selector=>document.querySelector(selector);
  const $$=selector=>[...document.querySelectorAll(selector)];
  const esc=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const price=value=>Number(value).toFixed(5);
  let busy=false, interval=5, animation=!matchMedia('(prefers-reduced-motion: reduce)').matches;
  const last30=data.candles.slice(-6);
  $('#rates').innerHTML=data.rates.map((row,index)=>`<tr class="${index===0?'selected':''}"><td>${row.pair}</td><td>${row.rate}</td><td>${row.day}</td></tr>`).join('');
  $('#questions').innerHTML=data.answers.map(answer=>`<button class="question" data-answer="${answer.id}" aria-pressed="false">${answer.question}</button>`).join('');
  $('#ohlc').innerHTML=last30.map(row=>`<tr><td>${row.time}</td>${['open','high','low','close'].map(key=>`<td>${price(row[key])}</td>`).join('')}</tr>`).join('');
  function candlesFor(minutes) {
    const count=minutes/5, candles=[];
    for(let i=0;i<data.candles.length;i+=count) {
      const group=data.candles.slice(i,i+count);
      candles.push({time:group[0].time,open:group[0].open,close:group.at(-1).close,high:Math.max(...group.map(p=>p.high)),low:Math.min(...group.map(p=>p.low))});
    }
    return candles;
  }
  function chart() {
    const candles=candlesFor(interval),width=680,height=285,left=63,right=625,top=22,bottom=251;
    const low=1.1170,high=1.1215,xstep=(right-left)/candles.length;
    const y=value=>top+(high-value)/(high-low)*(bottom-top);
    let svg=`<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="EUR/USD ${interval}-minute illustrative candlestick chart, 06:10 to 08:10 UTC"><title>Fixed design snapshot. Last price 1.12007. No live data.</title><defs><clipPath id="plot-clip"><rect x="${left}" y="${top}" width="${right-left}" height="${bottom-top}"/></clipPath><linearGradient id="replay-glow"><stop offset="0" stop-color="#00c895" stop-opacity="0"/><stop offset="1" stop-color="#00c895" stop-opacity=".09"/></linearGradient></defs><rect x="${left+(right-left)*.75}" y="${top}" width="${(right-left)*.25}" height="${bottom-top}" fill="#00c895" opacity=".06"/>`;
    for(let i=0;i<=9;i++) {
      const value=high-i*.0005,yp=y(value);
      svg+=`<line class="grid" x1="${left}" x2="${right}" y1="${yp}" y2="${yp}"/><text x="${left-9}" y="${yp+4}" text-anchor="end">${value.toFixed(4)}</text>`;
    }
    ['06:10','06:30','06:50','07:10','07:30','07:50','08:10'].forEach((time,i)=>{
      const x=left+(right-left)*i/6;svg+=`<line class="grid" x1="${x}" x2="${x}" y1="${top}" y2="${bottom}"/><text x="${x}" y="${bottom+22}" text-anchor="middle">${time}</text>`;
    });
    svg+=`<line class="axis" x1="${left}" x2="${left}" y1="${top}" y2="${bottom}"/><line class="axis" x1="${left}" x2="${right}" y1="${bottom}" y2="${bottom}"/><text class="highlight-label" x="${right-11}" y="${top+14}" text-anchor="end">LAST 30 MIN</text><g clip-path="url(#plot-clip)"><rect class="replay-sweep" x="${left-75}" y="${top}" width="75" height="${bottom-top}" fill="url(#replay-glow)"/>`;
    candles.forEach((candle,i)=>{
      const xp=left+xstep*(i+.5),body=Math.min(13,xstep*.55),up=candle.close>=candle.open;
      svg+=`<g class="${i===candles.length-1?'last-candle':''}"><title>${candle.time} / O ${price(candle.open)} H ${price(candle.high)} L ${price(candle.low)} C ${price(candle.close)}</title><line class="candle-wick" x1="${xp}" x2="${xp}" y1="${y(candle.high)}" y2="${y(candle.low)}"/><rect class="${up?'candle-up':'candle-down'}" x="${xp-body/2}" y="${y(Math.max(candle.open,candle.close))}" width="${body}" height="${Math.max(1.5,Math.abs(y(candle.open)-y(candle.close)))}"/></g>`;
    });
    svg+=`</g><line x1="${left}" x2="${right}" y1="${y(1.12007)}" y2="${y(1.12007)}" stroke="#00c895" stroke-dasharray="2 5" opacity=".3"/><rect x="${right+3}" y="${y(1.12007)-9}" width="52" height="18" fill="#00c895"/><text class="price-label" x="${right+7}" y="${y(1.12007)+3}">1.12007</text></svg>`;
    $('#chart').innerHTML=svg;$('#chart-label').textContent=interval+'-minute candles';
    $$('[data-interval]').forEach(button=>{const active=Number(button.dataset.interval)===interval;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
  }
  function syncAnimation() {
    document.body.classList.toggle('paused',!animation);$('#replay-toggle').textContent=animation?'Pause animation':'Play animation';$('#replay-toggle').setAttribute('aria-pressed',String(animation));$('#replay-status').innerHTML='<i></i> '+(animation?'Animated replay':'Replay paused');
  }
  function contextFor(id) {
    if(id==='last30') return last30;
    if(id==='feed') return {live_feed:false,trading_appliance:'not connected',agent_mesh:'prepared context only',llm_calls:0,live_orders:false};
    return {as_of:data.as_of,last:1.12007,bid:null,ask:null,open_30m:1.12032,high_30m:1.12095,low_30m:1.12007,change_pips:-2.5,source:'User-supplied design'};
  }
  function appendQuestion(text) {
    const el=document.createElement('article');el.className='message user';el.innerHTML='<div class="message-role">YOU</div><p></p>';el.querySelector('p').textContent=text;$('#transcript').append(el);
  }
  function appendAnswer(answer) {
    const el=document.createElement('article');el.className='message answer';el.dataset.response=answer.id;
    el.innerHTML=`<div class="message-role">DESK</div><p>${esc(answer.answer)}</p><p class="source">${esc(answer.source)}</p><details class="context"><summary>Context used <span>${answer.context}</span></summary><pre>${esc(JSON.stringify(contextFor(answer.id),null,2))}</pre></details>`;$('#transcript').append(el);
  }
  function setBusy(value) {
    busy=value;$$('#questions button, #chat-form button, #chat-input').forEach(element=>{element.disabled=value;});
  }
  async function ask(id,text) {
    if(busy)return;
    const answer=data.answers.find(answer=>answer.id===id);if(!answer)return;
    setBusy(true);$$('[data-answer]').forEach(button=>{const active=button.dataset.answer===id;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});
    appendQuestion(text||answer.question);
    const typing=document.createElement('div');typing.className='typing';typing.textContent='Loading prepared answer…';$('#transcript').append(typing);$('#transcript').scrollTop=$('#transcript').scrollHeight;
    if(innerWidth<=720) $('.chat-pane').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
    await new Promise(resolve=>setTimeout(resolve,450));typing.remove();appendAnswer(answer);setBusy(false);$('#transcript').scrollTop=$('#transcript').scrollHeight;
  }
  function route(text) {
    if(/feed|connect|live|appliance|mesh|llm|broker/i.test(text))return 'feed';
    if(/30|thirty|happen|move|change|range|half|last/i.test(text))return 'last30';
    if(/where|eur|price|quote|now|snapshot|bid|ask/i.test(text))return 'where';
    return null;
  }
  document.addEventListener('click',event=>{
    const question=event.target.closest('[data-answer]');if(question)ask(question.dataset.answer);
    const timeframe=event.target.closest('[data-interval]');if(timeframe){interval=Number(timeframe.dataset.interval);chart();}
    const tab=event.target.closest('[data-tab]');if(tab){const name=tab.dataset.tab;$$('[data-tab]').forEach(button=>{const active=button===tab;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});$$('.view').forEach(view=>{view.hidden=view.id!==name+'-view';});}
  });
  $('#replay-toggle').addEventListener('click',()=>{animation=!animation;syncAnimation();});
  $('#chat-form').addEventListener('submit',event=>{
    event.preventDefault();if(busy)return;const text=$('#chat-input').value.trim();if(!text)return;$('#chat-input').value='';const id=route(text);
    if(id)ask(id,text);else{appendQuestion(text);const el=document.createElement('article');el.className='message answer';el.innerHTML='<div class="message-role">DESK</div><p>Choose one of the three prepared questions: the current EUR/USD snapshot, the last 30 minutes, or the connection status.</p>';$('#transcript').append(el);$('#transcript').scrollTop=$('#transcript').scrollHeight;}
  });
  const scenarios={offline:{feed:false,spread:null,age:null,status:'Hold',reason:'A connected feed is required. Bid, ask and quote age are unavailable.'},wide:{feed:true,spread:3.2,age:2,status:'Hold: wide spread',reason:'The simulated spread exceeds the 2 pip limit.'},stale:{feed:true,spread:1,age:35,status:'Hold: stale quote',reason:'The simulated quote is older than the 15 second limit.'},ready:{feed:true,spread:1,age:2,status:'Eligible for review',reason:'All three checks pass in this simulated scenario. No order is sent.'}};
  function rules(){const s=scenarios[$('#scenario').value];$('#rule-posture').textContent=s.status;$('#rule-reason').textContent=s.reason;$('#rule-checks').innerHTML=[['Feed connected',s.feed?'Pass':'Not connected'],['Spread ≤ 2 pips',s.spread===null?'N/A':s.spread+' pips'],['Quote age ≤ 15s',s.age===null?'N/A':s.age+' seconds']].map(([label,value])=>`<div class="rule-check"><span>${label}</span><span>${value}</span></div>`).join('');}
  $('#scenario').addEventListener('change',rules);
  const initial=data.answers.find(answer=>answer.id==='last30');appendQuestion(initial.question);appendAnswer(initial);$('[data-answer="last30"]').classList.add('active');$('[data-answer="last30"]').setAttribute('aria-pressed','true');chart();syncAnimation();rules();
})();
