import nativeRegression from './vendor/webgazer-src/ridgeReg.mjs';
import util from './vendor/webgazer-src/util.mjs';
import params from './vendor/webgazer-src/params.mjs';

// WebGazer's original RidgeReg.addData/predict, seeded with the shared dataset.
// Own the camera in app.js; calling webgazer.begin() would open a second stream.
export class AdaptiveWebGazer {
  constructor({clock=()=>performance.now()}={}) {
    this.clock=clock; this.tracker=null; this.model=null; this.fitCount=0;
    this.latestEyes=null; this.latestFrameAt=-Infinity; this.lastMoveAt=-Infinity;
    this.onlineClicks=0; this.onlineMoves=0; this.predictionRefits=0;
    this.initialSamples=0; this.clickCapacity=0;
  }
  async init() {
    if (!window.webgazer) throw new Error('WebGazer 파일이 없습니다. setup_envs.py를 확인하세요.');
    window.webgazer.params.faceMeshSolutionPath=new URL('./mediapipe/face_mesh',window.location.href).href;
    window.webgazer.params.saveDataAcrossSessions=false;
    // Retain the preceding ZIP's no-output-smoothing comparison setting.
    params.applyKalmanFilter=false;
    this.tracker=new window.webgazer.tracker.TFFaceMesh();
    await this.tracker.init();
  }
  clearObservation() { this.latestEyes=null; this.latestFrameAt=-Infinity; }
  async extract(canvas) {
    const capturedAt=this.clock();
    this.clearObservation();
    let eyes;
    try {
      eyes=await this.tracker.getEyePatches(canvas,canvas,canvas.width,canvas.height);
    } catch(error) {
      if (error instanceof RangeError || error.name==='IndexSizeError') return null;
      throw error;
    }
    if (!eyes) return null;
    const features=util.getEyeFeats(eyes);
    if (features?.length!==120 || !features.every(Number.isFinite)) return null;
    this.latestEyes=eyes; this.latestFrameAt=capturedAt;
    return Array.from(features);
  }
  fit(samples) {
    if (this.model) throw new Error('초기 보정은 이미 완료되었습니다. 새 초기 보정은 재보정 버튼에서 시작하세요.');
    if (!samples.length) throw new Error('공통 보정 표본이 없습니다.');
    const dimensions=samples[0].features.length;
    if (!dimensions || samples.some(s=>s.features.length!==dimensions || !s.features.every(Number.isFinite)
      || s.target.length!==2 || !s.target.every(Number.isFinite))) throw new Error('유효하지 않은 보정 표본');
    params.applyKalmanFilter=false;
    const model=new nativeRegression.RidgeReg();
    // Native 50-click capacity would discard most of the initial 270 samples.
    // Enlarge the native ring once; future clicks still replace oldest entries.
    this.clickCapacity=samples.length+50;
    for (const key of ['screenXClicksArray','screenYClicksArray','eyeFeaturesClicks','dataClicks']) {
      model[key]=new util.DataWindow(this.clickCapacity);
    }
    for (const sample of samples) {
      model.screenXClicksArray.push([sample.target[0]]);
      model.screenYClicksArray.push([sample.target[1]]);
      model.eyeFeaturesClicks.push(sample.features.slice());
    }
    this.model=model; this.initialSamples=samples.length; this.fitCount=1;
    // RidgeReg computes its actual regression coefficients in predict(), as in
    // upstream. This count denotes shared initialization, not a lifetime fit cap.
    this.clearObservation();
  }
  recordInteraction(type,x,y) {
    const now=this.clock();
    if (!this.model || !this.latestEyes || !Number.isFinite(x) || !Number.isFinite(y)
      || now-this.latestFrameAt<0 || now-this.latestFrameAt>500 || !['click','move'].includes(type)) return false;
    if (type==='move' && now-this.lastMoveAt<params.moveTickSize) return false;
    // Actual library API. Clicks update the rolling dataset; moves contribute a
    // short native cursor trail. The next predict() refits from those samples.
    this.model.addData(this.latestEyes,[x,y],type);
    if (type==='click') this.onlineClicks++;
    else { this.onlineMoves++; this.lastMoveAt=now; }
    return true;
  }
  predict(features) {
    if (!features || !this.model || !this.latestEyes) return null;
    const result=this.model.predict(this.latestEyes);
    this.predictionRefits++;
    return result && Number.isFinite(result.x) && Number.isFinite(result.y) ? [result.x,result.y] : null;
  }
  stats() {
    return {initial_samples:this.initialSamples,initial_fit_count:this.fitCount,
      click_buffer_capacity:this.clickCapacity,click_buffer_samples:this.model?.eyeFeaturesClicks.length || 0,
      move_buffer_samples:this.model?.eyeFeaturesTrail.length || 0,
      online_clicks:this.onlineClicks,online_moves:this.onlineMoves,prediction_refits:this.predictionRefits};
  }
  async close() {
    this.clearObservation();
    if (this.tracker?.detector) await this.tracker.detector.dispose();
    this.tracker=null; this.model=null;
  }
}
