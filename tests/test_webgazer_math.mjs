// Numeric/protocol tests only. No tracker initialization, browser or camera.
import assert from 'node:assert/strict';
import {AdaptiveWebGazer} from '../web/webgazer-adapter.js';
import util from '../web/vendor/webgazer-src/util.mjs';

// Replace image-to-feature extraction only. addData, DataWindow, RidgeReg.predict
// and the numerical solver remain the actual unmodified upstream source.
const originalGetEyeFeats=util.getEyeFeats;
util.getEyeFeats=eyes=>eyes.testFeatures.slice();
let tests=0;
function test(name,run) { run(); tests++; console.log(`PASS: ${name}`); }
function fixture() {
  let now=Math.ceil(performance.now());
  const estimator=new AdaptiveWebGazer({clock:()=>now});
  const samples=Array.from({length:270},(_,i)=>{
    const u=(i%9)/8, v=Math.floor(i/9)/29;
    return {features:[1,u,v,u*v],target:[120+600*u,80+500*v]};
  });
  estimator.fit(samples);
  function eyes(features=[1,.5,.5,.25]) {
    estimator.latestEyes={testFeatures:features}; estimator.latestFrameAt=now;
  }
  return {estimator,samples,eyes,advance:ms=>{now+=ms;}};
}
try {
  test('all 270 common samples are seeded without the native 50-click truncation',()=>{
    const {estimator:e,samples,eyes}=fixture();
    assert.equal(e.stats().click_buffer_samples,270);
    assert.equal(e.stats().click_buffer_capacity,320);
    assert.deepEqual(e.model.eyeFeaturesClicks.data,samples.map(s=>s.features));
    eyes(); const p=e.predict([1,.5,.5,.25]);
    assert.ok(Math.abs(p[0]-420)<=1 && Math.abs(p[1]-330)<=1);
    samples[0].features[0]=123456;
    assert.equal(e.model.eyeFeaturesClicks.data[0][0],1);
  });
  test('real native click addData changes the subsequent prediction',()=>{
    const {estimator:e,eyes}=fixture(); eyes();
    const before=e.predict([1,.5,.5,.25]);
    for(let i=0;i<50;i++) assert.ok(e.recordInteraction('click',900,700));
    const after=e.predict([1,.5,.5,.25]);
    assert.ok(after[0]>before[0]+30 && after[1]>before[1]+30);
    assert.equal(e.stats().online_clicks,50);
    assert.equal(e.fitCount,1); // initial calibration once; subsequent learning exists
    assert.ok(e.stats().prediction_refits>=2);
  });
  test('real native mouse trail participates and uses 50ms throttling',()=>{
    const {estimator:e,eyes,advance}=fixture(); eyes();
    const before=e.predict([1,.5,.5,.25]);
    assert.ok(e.recordInteraction('move',900,700));
    assert.equal(e.recordInteraction('move',100,100),false);
    const after=e.predict([1,.5,.5,.25]);
    assert.ok(after[0]>before[0]);
    advance(50); eyes(); assert.ok(e.recordInteraction('move',900,700));
    assert.equal(e.stats().online_moves,2);
    for(let i=0;i<e.model.trailTimes.data.length;i++) e.model.trailTimes.data[i]=performance.now()-2000;
    const expired=e.predict([1,.5,.5,.25]);
    assert.deepEqual(expired,before);
  });
  test('missing/stale eyes and nonfinite coordinates cannot enter training',()=>{
    const {estimator:e,eyes,advance}=fixture();
    assert.equal(e.recordInteraction('click',1,1),false);
    eyes(); advance(501); assert.equal(e.recordInteraction('click',1,1),false);
    eyes(); assert.equal(e.recordInteraction('click',NaN,1),false);
    assert.equal(e.recordInteraction('other',1,1),false);
    assert.equal(e.stats().online_clicks,0);
  });
  test('switching away clears only observations and retains learned state',()=>{
    const {estimator:e,eyes}=fixture(); eyes(); e.recordInteraction('click',900,700);
    const model=e.model, before=e.stats();
    e.clearObservation();
    assert.equal(e.model,model);
    assert.deepEqual(e.stats(),before);
    assert.equal(e.recordInteraction('click',1,1),false);
    eyes(); assert.ok(e.recordInteraction('click',800,600));
    assert.equal(e.stats().online_clicks,2);
    assert.throws(()=>e.fit([{features:[1],target:[1,2]}]),/초기 보정/);
  });
  test('long usage has bounded buffers and explicit recalibration resets state',()=>{
    const {estimator:e,eyes,advance}=fixture(); eyes();
    for(let i=0;i<1200;i++) {
      eyes(); e.recordInteraction('click',i%1000,500); e.recordInteraction('move',i%1000,500); advance(50);
    }
    assert.equal(e.stats().click_buffer_samples,320);
    assert.ok(e.stats().move_buffer_samples<=10);
    assert.equal(e.stats().online_clicks,1200);
    assert.equal(e.stats().online_moves,1200);
    const fresh=fixture().estimator;
    assert.equal(fresh.stats().online_clicks,0);
    assert.equal(fresh.stats().click_buffer_samples,270);
  });
} finally { util.getEyeFeats=originalGetEyeFeats; }
console.log(`${tests} tests passed; no tracker, webcam, server or app was started.`);
