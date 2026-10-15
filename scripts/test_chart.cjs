const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const elements = new Map();
const element = id => {
  if(!elements.has(id)) elements.set(id, {clientWidth:900, attributes:{}, handlers:{},
    setAttribute(k,v){this.attributes[k]=v;}, removeAttribute(k){delete this.attributes[k];},
    addEventListener(k,v){this.handlers[k]=v;}});
  return elements.get(id);
};
const buttons = [60,180,300].map(n=>Object.assign(element(String(n)),{dataset:{window:String(n)}}));
const intervals=[5,15,30].map(n=>Object.assign(element('interval'+n),{dataset:{interval:String(n)}}));
const context = {window:{}, document:{getElementById:element,querySelectorAll:selector=>selector==='[data-window]'?buttons:intervals},
  setInterval(){}, ResizeObserver:class {observe(){}}, Date, Number, Map};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/chart.js','utf8'), context);
const chart = context.window.SamFxChart;
const probe=[1.1,1.1004,1.0998,1.1001,1.1002].map((mid,i)=>({timestamp:new Date(1700000000000+i*1000).toISOString(),mid,bid:mid-.00004,ask:mid+.00004}));
chart.update(probe.at(-1),probe);
element('chart').handlers.keydown({key:'ArrowRight',preventDefault(){}});
assert.match(element('chart-tooltip').textContent,/O 1.10000  H 1.10040\nL 1.09980  C 1.10020/,'OHLC must come from the actual source observations');
const history = Array.from({length:301},(_,i)=>({timestamp:new Date(1700000000000+i*1000).toISOString(),mid:1.1+i*.000001,bid:1.09996+i*.000001,ask:1.10004+i*.000001}));
chart.update(history.at(-1),history);
assert.match(element('chart-coverage').textContent,/296 source observations/);
assert.match(element('price-change').textContent,/\+2.9 pips/);
buttons[0].handlers.click();
assert.match(element('chart-coverage').textContent,/56 source observations/);
chart.update(history.at(-1),history);
assert.match(element('chart-coverage').textContent,/56 source observations/,'duplicate SSE snapshots must not add points');
const afterGap = {...history.at(-1),timestamp:new Date(1700000310000).toISOString()};
chart.update(afterGap);
assert.equal((element('chart-candles').innerHTML.match(/class="candle /g)||[]).length,11,'missing buckets must not invent candles');
assert(!element('price-path').attributes.d.includes('NaN'));
assert.match(element('chart-candles').innerHTML,/candle up/);
intervals[1].handlers.click();
assert.match(element('window-range').textContent,/15-second candles/);
assert.equal((element('chart-candles').innerHTML.match(/class="candle /g)||[]).length,4);
element('chart-average').handlers.click();
assert.equal(element('price-path').attributes.d,'','average toggle must hide the indicator');
chart.disconnect();
assert.match(element('chart-status').textContent,/paused/);
element('chart').handlers.keydown({key:'ArrowLeft',preventDefault(){}});
assert.match(element('chart-tooltip').textContent,/O .*H .*\nL .*C /);
assert.match(element('chart-tooltip').textContent,/BID.*ASK/);
console.log('Chart checks passed: source OHLC candles, intervals, missing buckets, moving-average toggle, deduplication, stale state and keyboard inspection.');
