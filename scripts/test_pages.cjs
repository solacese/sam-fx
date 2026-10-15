const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
function load(saved={}) {
  let tick, state;
  const storage={...saved};
  const context={window:{},crypto:{randomUUID},localStorage:{getItem:k=>storage[k]||null,setItem:(k,v)=>storage[k]=v},
    setInterval:fn=>{tick=fn;},setTimeout:()=>{},URL,Blob,
    document:{querySelector:()=>({addEventListener(){}})}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('dist/pages/demo-data.js','utf8'),context);
  vm.runInContext(fs.readFileSync('web/demo.js','utf8'),context);
  context.window.SamFxDemo.start(s=>state=s);
  return {api:context.window.SamFxDemo,tick:()=>tick(),get state(){return state;},storage};
}
(async()=>{
  for(const [scenario,cause,health] of [['market','MARKET','HEALTHY'],['infrastructure','INFRASTRUCTURE','DEGRADED'],['feed_loss','INFRASTRUCTURE','UNAVAILABLE'],['telemetry_loss','UNCLEAR','UNKNOWN'],['capacity','BOTH','DEGRADED']]) {
    const demo=load(); await demo.api.post('/api/scenarios/'+scenario);
    for(let i=0;i<9;i++) demo.tick();
    assert.equal(demo.state.assessment.likely_cause,cause,scenario);
    assert.equal(demo.state.service_condition,health);
    assert.equal(demo.state.incidents.length,scenario==='market'?0:1);
    if(scenario==='market') continue;
    const id=demo.state.incidents[0].incident_id;
    await demo.api.post(`/api/incidents/${id}/acknowledge`);
    assert.equal(demo.state.incidents[0].status,'ACKNOWLEDGED');
    await assert.rejects(demo.api.post(`/api/incidents/${id}/resolve`));
    await demo.api.post('/api/recover');
    for(let i=0;i<5;i++) demo.tick();
    assert.equal(demo.state.incidents[0].status,'RECOVERED');
    await demo.api.post(`/api/incidents/${id}/resolve`);
    assert.equal(demo.state.incidents[0].status,'RESOLVED');
    const restored=load(demo.storage);
    assert.equal(restored.state.incidents[0].status,'RESOLVED');
    await demo.api.post('/api/scenarios/'+scenario);
    for(let i=0;i<5;i++) demo.tick();
    assert.equal(demo.state.incidents.length,2);
    assert.notEqual(demo.state.incidents[0].incident_id,id);
  }
  for(const scenario of ['tokyo_burst','tcp_pressure','queue_pressure','market_only','aiops_unknown']) {
    const demo=load(); await demo.api.post('/api/scenarios/'+scenario);
    for(let i=0;i<10;i++) demo.tick();
    assert.equal(demo.state.llm_enabled,false,'Pages must never enable model calls');
    if(scenario==='market_only') {
      assert.equal(demo.state.aiops.status,'WITHIN_LIMITS');
      assert.equal(demo.state.assessment,null);
    } else {
      assert.equal(demo.state.incidents.length,1);
      assert.equal(demo.state.assessment.graph.nodes.length,4);
      assert.equal(demo.state.assessment.checks.length,3);
      assert.equal(demo.state.assessment.model,'deterministic-fallback');
      if(scenario==='aiops_unknown') assert.equal(demo.state.assessment.graph.edges.length,0);
      await demo.api.post('/api/recover');
      for(let i=0;i<5;i++)demo.tick();
      assert.equal(demo.state.incidents[0].status,'RECOVERED');
    }
  }
  const html=fs.readFileSync('dist/pages/index.html','utf8');
  assert(!html.includes('/assets/') && !html.includes('/api/'));
  console.log('Pages checks passed: five AIOps cases, five legacy scenarios, prepared causes, lifecycle, persistence, distinct IDs, relative assets.');
})().catch(e=>{console.error(e);process.exit(1);});
