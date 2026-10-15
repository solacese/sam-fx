const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const elements = new Map();
const element = id => {
  if(!elements.has(id)) elements.set(id, {clientWidth:900, attributes:{}, handlers:{},
    setAttribute(k,v){this.attributes[k]=v;}, removeAttribute(k){delete this.attributes[k];},
    addEventListener(k,v){this.handlers[k]=v;}});
  return elements.get(id);
};
const buttons = [60,180,300].map(n=>Object.assign(element(String(n)),{dataset:{window:String(n)}}));
const context = {window:{}, document:{getElementById:element,querySelectorAll:()=>buttons},
  setInterval(){}, ResizeObserver:class {observe(){}}, Date, Number, Map};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/chart.js','utf8'), context);
const chart = context.window.SamFxChart;
const history = Array.from({length:301},(_,i)=>({timestamp:new Date(1700000000000+i*1000).toISOString(),mid:1.1+i*.000001,bid:1.09996+i*.000001,ask:1.10004+i*.000001}));
chart.update(history.at(-1),history);
assert.match(element('chart-coverage').textContent,/301 observations/);
assert.match(element('price-change').textContent,/\+3.0 pips/);
buttons[0].handlers.click();
assert.match(element('chart-coverage').textContent,/61 observations/);
chart.update(history.at(-1),history);
assert.match(element('chart-coverage').textContent,/61 observations/,'duplicate SSE snapshots must not add points');
const afterGap = {...history.at(-1),timestamp:new Date(1700000310000).toISOString()};
chart.update(afterGap);
assert.equal((element('price-path').attributes.d.match(/M/g)||[]).length,2,'missing ticks must break the line');
chart.disconnect();
assert.match(element('chart-status').textContent,/paused/);
element('chart').handlers.keydown({key:'ArrowLeft',preventDefault(){}});
assert.match(element('chart-tooltip').textContent,/BID.*ASK/);
console.log('Chart checks passed: rolling window, exact source prices, deduplication, stream gaps, stale state and keyboard inspection.');
