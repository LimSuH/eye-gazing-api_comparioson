import {AdaptiveWebGazer} from './webgazer-adapter.js';

const $=id=>document.getElementById(id);
const names={eyetrax:'EyeTrax',gazefollower:'GazeFollower',eyegestures:'EyeGestures',webgazer:'WebGazer'};
const video=$('video'), frameCanvas=document.createElement('canvas');
const frameContext=frameCanvas.getContext('2d',{willReadFrequently:true});
const gaze=$('gazeLayer'), gazeContext=gaze.getContext('2d');
const outline=$('referenceLayer'), outlineContext=outline.getContext('2d');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const painted=()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
let cfg, token, phase='idle', engine='eyetrax', stream=null, webgazer=null;
let session=null, epoch=0, busy=false, running=false, loopPromise=Promise.resolve();
let viewport=null, seq=0, collecting=false, settleUntil=0, targetIndex=0, counts=[];
let wgSamples=[], reference=null, livePose=null, calibrationAudit=null, lastPoint=null;
let lastFrameAt=0, fps=0;

async function api(path,data={}) {
  try {
    return await window.gazeNetwork.request(path,{method:'POST',headers:{'Content-Type':'application/json','X-Gaze-Token':token},body:JSON.stringify(data)},
      {timeoutMs:path==='/api/end' ? 10000 : 180000});
  } catch(error) {
    if (path==='/api/frame') {
      const recovered=await window.gazeNetwork.recoverFrame(error,{sessionId:data.session_id,seq:data.seq,token});
      if (recovered) return recovered;
    }
    await window.gazeNetwork.explainFailure(error);
    window.gazeNetwork.report(error);
    throw error;
  }
}
function message(text) { $('message').textContent=text; }
function sameViewport() { return viewport && viewport[0]===innerWidth && viewport[1]===innerHeight; }
function finitePoint(p) { return Array.isArray(p) && p.length===2 && p.every(Number.isFinite); }
function updateControls() {
  const ready=phase==='tracking';
  document.body.classList.toggle('calibrating',['calibrating','fitting'].includes(phase));
  $('calibrationHUD').hidden=!['calibrating','fitting'].includes(phase);
  $('target').hidden=phase!=='calibrating';
  $('target').disabled=phase!=='calibrating';
  $('start').disabled=busy || !cfg || !['idle','stopped'].includes(phase);
  $('recalibrate').disabled=busy || !session;
  $('stop').disabled=busy || !stream;
  $('devices').disabled=busy || !!stream;
  $('camera').disabled=busy || !!stream;
  $('capture').disabled=phase!=='calibrating' || collecting || document.hidden;
  $('cancel').disabled=busy;
  document.querySelectorAll('.engine').forEach(b=>{
    b.disabled=!ready || busy;
    b.classList.toggle('selected',b.dataset.engine===engine);
  });
  $('activeName').textContent=names[engine];
  updateOnlineStatus();
  $('lockStatus').textContent=calibrationAudit
    ? `초기 보정 공통 ${calibrationAudit.samples}프레임 · ID ${calibrationAudit.calibration_id.slice(0,12)} · WebGazer 추가 학습 ON`
    : '공통 9점 보정 전 · 네 엔진의 동일 프레임을 모읍니다.';
}
function setPhase(value) { phase=value; updateControls(); }
function updateOnlineStatus() {
  const stats=webgazer?.stats();
  $('onlineStatus').textContent=calibrationAudit && stats
    ? `WebGazer 추가 학습: 클릭 ${stats.online_clicks}회 · 이동 ${stats.online_moves}회 · ${engine==='webgazer' ? '선택 중: 클릭/커서 학습 활성' : '다른 엔진 선택 중: 학습 상태 보관'}`
    : 'WebGazer는 공통 보정 후 선택된 동안 클릭·마우스 이동으로 추가 학습합니다.';
}
function handleOnlineInteraction(event) {
  if (!event.isTrusted || busy || !running || document.hidden || engine!=='webgazer'
    || phase!=='tracking' || !sameViewport()) return;
  // Management buttons must not silently add labels when switching/restarting.
  if (event.target?.closest?.('button,select,input,summary,a')) return;
  if (event.clientX<0 || event.clientY<0 || event.clientX>=viewport[0] || event.clientY>=viewport[1]) return;
  if (webgazer.recordInteraction(event.type==='click'?'click':'move',event.clientX,event.clientY)) updateOnlineStatus();
}
document.addEventListener('click',handleOnlineInteraction,true);
document.addEventListener('mousemove',handleOnlineInteraction,true);
function locateTarget(target) {
  if (!Array.isArray(target) || target.length!==2 || !target.every(Number.isFinite)) {
    throw new Error('서버가 보정점 위치를 전달하지 않았습니다. 서버와 브라우저 파일 버전을 확인하세요.');
  }
  const node=$('target');
  node.style.left=`${target[0]}px`;
  node.style.top=`${target[1]}px`;
  const rect=node.getBoundingClientRect();
  const margin=8;
  if (rect.left<margin || rect.top<margin || rect.right>innerWidth-margin || rect.bottom>innerHeight-margin) {
    throw new Error(`보정점 ${targetIndex+1}이 화면 안에 배치되지 않았습니다. 창 크기와 브라우저 배율을 확인하세요.`);
  }
}
function calibrationText(reasons={}) {
  if (phase!=='calibrating') return;
  locateTarget(cfg.calibration_targets[targetIndex]);
  $('calibrationTitle').textContent=`공통 보정 ${targetIndex+1} / ${cfg.calibration_point_count} · ${counts[targetIndex] || 0} / ${cfg.samples_per_point}프레임`;
  const missing=Object.entries(reasons).filter(([,v])=>v!=='ok').map(([k,v])=>`${names[k] || k}: ${v}`).join(' / ');
  $('calibrationInfo').textContent=collecting
    ? (missing ? `머리는 고정하고 파란 점을 보세요. 수집 대기: ${missing}` : '머리를 고정하고 파란 점을 계속 보세요. 네 엔진이 모두 인식한 프레임만 저장합니다.')
    : '파란 점을 본 뒤 SPACE 또는 현재 점 수집을 누르세요. 0.8초 후 수집합니다. 머리는 끝까지 같은 자세로 유지하세요.';
}
function beginCapture() {
  if (phase!=='calibrating' || collecting || document.hidden) return;
  collecting=true; settleUntil=performance.now()+cfg.settle_ms;
  updateControls(); calibrationText();
}
function releaseCamera() {
  stream?.getTracks().forEach(track=>track.stop());
  stream=null; video.srcObject=null;
}
async function quiesce({release=false}={}) {
  running=false; epoch++; collecting=false; lastPoint=null;
  webgazer?.clearObservation();
  if (release) releaseCamera();
  await loopPromise;
  if (webgazer) { await webgazer.close(); webgazer=null; }
}
async function openCamera() {
  if (stream) return;
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('Chrome/Edge에서 http://localhost:8765 로 접속하세요.');
  const device=$('camera').value;
  stream=await navigator.mediaDevices.getUserMedia({audio:false,video:{width:{ideal:640},height:{ideal:480},...(device ? {deviceId:{exact:device}} : {})}});
  video.srcObject=stream;
  await video.play();
  if (!video.videoWidth) await new Promise((resolve,reject)=>{
    video.addEventListener('loadeddata',resolve,{once:true});
    video.addEventListener('error',()=>reject(new Error('웹캠 영상을 읽지 못했습니다.')),{once:true});
  });
  stream.getVideoTracks()[0].addEventListener('ended',()=>invalidate('카메라 연결이 끊어졌습니다. 카메라 종료 후 다시 시작하세요.'));
}
async function startCalibration() {
  if (busy || !cfg) return;
  busy=true; updateControls();
  // Request fullscreen synchronously in the button's user gesture.
  const fullscreen=!document.fullscreenElement && document.documentElement.requestFullscreen
    ? document.documentElement.requestFullscreen().catch(()=>null) : Promise.resolve();
  try {
    await quiesce();
    setPhase('starting');
    await fullscreen; await painted();
    message('localhost 연결과 필수 파일을 확인합니다. 아직 카메라를 열지 않습니다.');
    await window.gazeNetwork.assertAssets();
    message('웹캠과 네 엔진을 준비합니다. 최초 실행은 모델 초기화 때문에 시간이 걸릴 수 있습니다.');
    await openCamera();
    const scale=Math.min(640/video.videoWidth,480/video.videoHeight,1);
    frameCanvas.width=Math.round(video.videoWidth*scale);
    frameCanvas.height=Math.round(video.videoHeight*scale);
    outline.width=frameCanvas.width; outline.height=frameCanvas.height;
    $('previewStack').style.aspectRatio=`${frameCanvas.width}/${frameCanvas.height}`;
    viewport=[innerWidth,innerHeight];
    reference=null; livePose=null; calibrationAudit=null; wgSamples=[];
    seq=0; targetIndex=0; counts=Array(cfg.calibration_point_count).fill(0); lastPoint=null;
    $('coordinates').textContent='—';
    webgazer=new AdaptiveWebGazer();
    await webgazer.init();
    // /api/start replaces the old server session and closes it on failure.
    // Do not send /api/end with a stale ID if the new initialization fails.
    session=null;
    const reply=await api('/api/start',{width:viewport[0],height:viewport[1],camera_size:[frameCanvas.width,frameCanvas.height]});
    session=reply.session_id;
    cfg.calibration_targets=reply.calibration_targets;
    if (!sameViewport()) throw new Error('준비 중 창 크기가 바뀌었습니다. 재보정을 누르세요.');
    counts=reply.counts; collecting=false; busy=false; setPhase('calibrating');
    calibrationText(); message('');
    running=true;
    const generation=epoch;
    loopPromise=frameLoop(generation).catch(error=>{ if (generation===epoch) invalidate(error.message); });
  } catch(error) {
    running=false; releaseCamera();
    if (webgazer) { try { await webgazer.close(); } catch {} webgazer=null; }
    if (session) { try { await api('/api/end',{session_id:session}); } catch {} session=null; }
    setPhase('stopped');
    message(`시작 실패: ${error.message} Python 터미널도 확인하세요. 자동으로 다른 엔진을 대신 실행하지 않습니다.`);
  } finally { busy=false; updateControls(); }
}
async function stop() {
  if (busy) return;
  busy=true; updateControls();
  try {
    await quiesce({release:true});
    if (session) await api('/api/end',{session_id:session});
  } catch(error) { message(error.message); }
  finally {
    session=null; calibrationAudit=null; livePose=null; busy=false; setPhase('stopped');
    $('trackingStatus').textContent='카메라가 종료되었습니다. 다시 시작하면 새 공통 보정을 진행합니다.';
  }
}
function invalidate(reason) {
  if (['idle','stopped','invalid'].includes(phase)) return;
  running=false; epoch++; collecting=false; lastPoint=null;
  webgazer?.clearObservation();
  setPhase('invalid');
  $('coordinates').textContent='—';
  $('trackingStatus').textContent='추적 중지 · 자동 재보정하지 않습니다.';
  message(`${reason} 초기 보정 화면은 자동으로 열지 않습니다. 재보정 버튼으로 다시 시작하세요.`);
}
async function completeCalibration(generation) {
  setPhase('fitting');
  $('calibrationTitle').textContent='공통 초기 보정으로 네 모델을 준비합니다';
  $('calibrationInfo').textContent='동일한 프레임 ID와 목표 좌표를 확인합니다. 추가 보정 화면은 없습니다.';
  await painted();
  if (generation!==epoch) return;
  webgazer.fit(wgSamples);
  const result=await api('/api/finish',{session_id:session,webgazer_frame_ids:wgSamples.map(s=>s.seq)});
  if (generation!==epoch) return;
  calibrationAudit={...result.audit,webgazer_initial_fit_count_verified_in_browser:webgazer.fitCount};
  wgSamples=[];
  setPhase('tracking');
  message('공통 초기 보정 완료. WebGazer를 선택하면 클릭·마우스 이동으로 추가 학습합니다. 기준 실루엣은 고정됩니다.');
}
async function frameLoop(generation) {
  while (running && generation===epoch) {
    if (!sameViewport()) { invalidate('창 크기 또는 전체화면 상태가 바뀌었습니다.'); break; }
    if (document.hidden || phase==='fitting' || (phase==='calibrating' && (!collecting || performance.now()<settleUntil))) {
      await delay(40); continue;
    }
    if (!['calibrating','tracking'].includes(phase)) break;
    if (video.readyState<2) { await delay(40); continue; }
    const calibrating=phase==='calibrating', selected=engine, pointId=targetIndex;
    // Exactly one immutable RGB image feeds all four engines during calibration.
    // PNG is lossless; the CSS mirror applies to preview only, never to this canvas.
    frameContext.drawImage(video,0,0,frameCanvas.width,frameCanvas.height);
    const encoded=frameCanvas.toDataURL('image/png').split(',')[1];
    const features=(calibrating || selected==='webgazer') ? await webgazer.extract(frameCanvas) : null;
    if (generation!==epoch) break;
    const frameId=seq++;
    const response=await api('/api/frame',{session_id:session,seq:frameId,viewport,
      mode:calibrating?'collect':'track',engine:selected,target_id:pointId,
      webgazer_valid:!!features,image:encoded});
    if (generation!==epoch) break;
    if (calibrating) {
      if (response.accepted) {
        if (!features) throw new Error('공통 보정 프레임 불일치');
        wgSamples.push({seq:frameId,features,target:cfg.calibration_targets[pointId].slice()});
      }
      if (wgSamples.length!==response.accepted_count) throw new Error('보정 응답 누락: 네 엔진의 프레임 수가 다릅니다.');
      // Frozen baseline: never replace this on inference or engine switches.
      if (!reference && response.reference) reference=response.reference;
      counts=response.counts;
      if (response.point_index!==targetIndex) {
        targetIndex=response.point_index; collecting=false; updateControls();
      }
      if (targetIndex===cfg.calibration_point_count) await completeCalibration(generation);
      else calibrationText(response.reasons);
    } else {
      const point=selected==='webgazer' ? webgazer.predict(features) : response.point;
      if (selected!==engine) webgazer.clearObservation();
      const valid=finitePoint(point), now=performance.now();
      livePose=response.live_pose;
      if (selected===engine) {
        lastPoint=valid ? {point,at:now} : null;
        fps=lastFrameAt ? .8*fps+.2*(1000/(now-lastFrameAt)) : 0;
        lastFrameAt=now;
        $('coordinates').textContent=valid ? `${point[0].toFixed(0)}, ${point[1].toFixed(0)} px` : '—';
        $('trackingStatus').textContent=valid
          ? `${names[selected]} · 약 ${fps.toFixed(1)}회/초 · ${selected==='webgazer'?'추가 학습 ON':'초기 보정 사용'}${point[0]<0 || point[1]<0 || point[0]>=viewport[0] || point[1]>=viewport[1] ? ' · 화면 밖 예측 (점만 가장자리에 표시)' : ''}`
          : `${names[selected]} · 얼굴/눈을 인식하지 못했습니다. 마지막 응시점은 숨깁니다.`;
      }

    }
    await delay(8);
  }
}
function selectEngine(name) {
  if (phase!=='tracking' || busy || !names[name]) return;
  engine=name; lastPoint=null; lastFrameAt=0; fps=0;
  webgazer?.clearObservation();
  $('coordinates').textContent='—';
  $('trackingStatus').textContent=`${names[name]} 출력으로 전환 중 · 기존 보정·학습 상태 유지`;
  updateControls();
}
function drawPolygon(points,color,width,fill=false) {
  if (!points?.length) return;
  outlineContext.beginPath();
  points.forEach(([x,y],i)=>outlineContext[i?'lineTo':'moveTo'](x*outline.width,y*outline.height));
  outlineContext.closePath(); outlineContext.strokeStyle=color; outlineContext.lineWidth=width;
  if (fill) { outlineContext.fillStyle='rgba(86,229,192,.06)'; outlineContext.fill(); }
  outlineContext.stroke();
}
function render(now) {
  if (gaze.width!==innerWidth || gaze.height!==innerHeight) { gaze.width=innerWidth; gaze.height=innerHeight; }
  gazeContext.clearRect(0,0,gaze.width,gaze.height);
  if (phase==='tracking' && lastPoint && now-lastPoint.at<350) {
    const [rawX,rawY]=lastPoint.point;
    const x=Math.min(gaze.width-12,Math.max(12,rawX)),y=Math.min(gaze.height-12,Math.max(12,rawY));
    gazeContext.beginPath(); gazeContext.arc(x,y,10,0,Math.PI*2);
    gazeContext.fillStyle='rgba(86,229,192,.28)'; gazeContext.fill();
    gazeContext.strokeStyle='#56e5c0'; gazeContext.lineWidth=2; gazeContext.stroke();
    gazeContext.beginPath(); gazeContext.arc(x,y,3,0,Math.PI*2); gazeContext.fillStyle='#e8fff8'; gazeContext.fill();
  }
  outlineContext.clearRect(0,0,outline.width,outline.height);
  if (reference) {
    drawPolygon(reference.silhouette,'#56e5c0',3,true);
    drawPolygon(reference.head,'#56e5c0',3);
    drawPolygon(livePose?.head,'rgba(255,255,255,.85)',1.5);
    const current=livePose?.center;
    $('poseStatus').textContent=current
      ? `고정 기준 대비 · 좌우 ${(-100*(current[0]-reference.center[0])).toFixed(1)}% · 상하 ${(100*(current[1]-reference.center[1])).toFixed(1)}% · 머리 크기 ${(100*livePose.head_width/reference.head_width).toFixed(0)}%`
      : '청록색 머리·실루엣 = 첫 보정 자세 (고정). 현재 머리 윤곽은 추적 중 표시됩니다.';
  } else $('poseStatus').textContent='첫 공통 보정 프레임에서 머리·실루엣을 고정합니다.';
  requestAnimationFrame(render);
}
$('start').onclick=startCalibration;
$('recalibrate').onclick=startCalibration;
$('stop').onclick=stop;
$('cancel').onclick=stop;
$('capture').onclick=beginCapture;
$('target').onclick=beginCapture;
document.querySelectorAll('.engine').forEach(button=>{ button.onclick=()=>selectEngine(button.dataset.engine); });
$('devices').onclick=async()=>{
  if (busy || stream) return;
  busy=true; updateControls();
  let temporary;
  try {
    temporary=await navigator.mediaDevices.getUserMedia({video:true,audio:false});
    const devices=(await navigator.mediaDevices.enumerateDevices()).filter(d=>d.kind==='videoinput');
    $('camera').replaceChildren(new Option('기본 웹캠',''),...devices.map((d,i)=>new Option(d.label || `카메라 ${i+1}`,d.deviceId)));
    message('카메라를 고른 다음 시작하세요. 목록 확인용 카메라는 종료했습니다.');
  } catch(error) { message(`카메라 목록: ${error.message}`); }
  finally { temporary?.getTracks().forEach(t=>t.stop()); busy=false; updateControls(); }
};
document.addEventListener('keydown',event=>{
  if (event.code==='Space' && phase==='calibrating') { event.preventDefault(); beginCapture(); }
});
window.addEventListener('resize',()=>{
  if (['calibrating','fitting','tracking'].includes(phase) && !sameViewport()) invalidate('창 크기가 바뀌었습니다.');
});
document.addEventListener('visibilitychange',()=>{
  if (!document.hidden) { updateControls(); return; }
  lastPoint=null; collecting=false; webgazer?.clearObservation(); updateControls(); calibrationText();
});
window.addEventListener('pagehide',()=>{
  running=false; epoch++; releaseCamera();
  if (session && token) void fetch('/api/end',{method:'POST',keepalive:true,headers:{'Content-Type':'application/json','X-Gaze-Token':token},body:JSON.stringify({session_id:session})}).catch(()=>{});
});
try {
  cfg=await window.gazeNetwork.request('/api/config'); token=cfg.token; delete cfg.token;
  message('준비 완료. 화면을 고정한 뒤 시작하세요. 카메라 영상은 이 컴퓨터의 localhost로만 전달합니다.');
} catch(error) { window.gazeNetwork.report(error); message(`서버 연결 실패: ${error.message}`); }
updateControls(); requestAnimationFrame(render);
