// Runs before WebGazer/app modules so their load failures remain visible.
// Diagnostic requests only read local HTTP resources; never open a camera/model.
(() => {
  'use strict';
  const entries=[];
  const $=id=>document.getElementById(id);
  function displayURL(value) {
    try {
      const url=new URL(value,location.href);
      return `${url.origin}${url.pathname}`; // Do not include query credentials.
    } catch { return String(value); }
  }
  function render() {
    if (entries.length && $('networkLog')) $('networkLog').textContent=entries.join('\n\n');
    if (entries.length && $('message')) $('message').textContent=entries.at(-1);
  }
  function log(text) {
    entries.push(String(text));
    if (entries.length>40) entries.shift();
    render();
  }
  function report(error) {
    const text=error?.message || String(error);
    log(text);
    if ($('networkPanel')) $('networkPanel').open=true;
    if ($('message')) $('message').textContent=text;
  }
  class RequestFailure extends Error {
    constructor(kind,url,detail) {
      super(`${detail}\n요청 주소: ${displayURL(url)}`);
      this.name='RequestFailure'; this.kind=kind; this.url=displayURL(url);
      this.status=null;
    }
  }
  function localURL(path) {
    const url=new URL(path,location.href);
    if (location.protocol!=='http:' || !['localhost','127.0.0.1'].includes(location.hostname)) {
      throw new Error('index.html을 직접 열지 마세요. run.py의 서버 준비 메시지를 확인하고 터미널에 표시된 http://127.0.0.1:포트/ 주소로 접속하세요.');
    }
    if (url.origin!==location.origin) throw new Error(`외부 요청은 허용하지 않습니다: ${displayURL(url)}`);
    return url.href;
  }
  async function request(path,options={}, {timeoutMs=10000,head=false,expectedBytes=null}={}) {
    const url=localURL(path);
    const controller=new AbortController();
    let expired=false;
    let stage='connection', status=null;
    const timer=setTimeout(()=>{ expired=true; controller.abort(); },timeoutMs);
    try {
      const response=await fetch(url,{...options,cache:'no-store',redirect:'error',signal:controller.signal});
      stage='response_body'; status=response.status;
      if (!response.ok) {
        let detail=`HTTP ${response.status}`;
        if (!head) {
          try {
            const body=await response.json();
            if (body.error) detail+=` · ${body.error}`;
          } catch(error) { if (expired) throw error; }
        }
        // Do not retry POST: the server may already have accepted calibration data.
        const failure=new RequestFailure('http',url,detail+(response.status===404
          ? ' · 파일 또는 경로가 없습니다. 최신 ZIP과 브라우저 파일 설치 상태를 확인하세요.' : ''));
        failure.status=status;
        throw failure;
      }
      if (head) {
        const length=response.headers.get('Content-Length');
        if (Number.isInteger(expectedBytes) && length!==null && Number(length)!==expectedBytes) {
          throw new RequestFailure('size',url,`파일 크기 불일치: 원본 ${expectedBytes} bytes, 응답 ${length} bytes. ZIP 전체를 다시 풀어 주세요.`);
        }
        return {status:response.status};
      }
      try { return await response.json(); }
      catch(error) {
        if (expired || error.name!=='SyntaxError') throw error;
        throw new RequestFailure('json',url,'JSON 응답이 아닙니다. 다른 서버/포트 또는 프록시 응답인지 확인하세요.');
      }
    } catch(error) {
      if (error instanceof RequestFailure) throw error;
      const detail=expired
        ? `${timeoutMs/1000}초 동안 응답이 끝나지 않았습니다. Python 터미널을 확인하세요. 서버 작업은 계속 진행 중일 수 있으며 요청을 자동 재전송하지 않습니다.`
        : stage==='response_body'
          ? `HTTP ${status} 응답 헤더는 받았지만 응답 본문을 끝까지 읽지 못했습니다. F12 → Network의 오류 코드를 확인하세요.`
          : 'HTTP 응답 헤더를 받기 전에 요청이 실패했습니다. F12 → Network의 오류 코드를 확인하세요.';
      const failure=new RequestFailure(expired?'timeout':'network',url,detail);
      failure.stage=stage; failure.status=status;
      throw failure;
    } finally { clearTimeout(timer); }
  }
  async function health() {
    const result=await request('/api/health');
    if (result.application!=='gaze-api-compare' || !Array.isArray(result.web_files)) {
      throw new RequestFailure('server',localURL('/api/health'),'예상한 Gaze Compare 서버가 아닙니다. 이전 서버를 종료하고 수정 ZIP의 run.py를 다시 실행하세요.');
    }
    return result;
  }
  async function assertAssets() {
    const result=await health();
    const missing=result.web_files.filter(file=>!file.exists || (Number.isInteger(file.expected_bytes) && file.bytes!==file.expected_bytes));
    if (missing.length) throw new Error('필수 로컬 파일이 없거나 원본 크기와 다릅니다:\n'
      +missing.map(file=>displayURL(file.url)).join('\n')
      +'\nZIP 전체를 다시 풀어 주세요. 브라우저 파일만 손상됐다면 python setup_envs.py --only webgazer로 동봉 원본에서 복원할 수 있습니다. 다운로드하지 않습니다.');
    return result;
  }
  async function explainFailure(error) {
    // A failed POST may have been committed. Only probe the read-only endpoint;
    // never replay a calibration frame or create a replacement session here.
    if (!error || error.explained) return;
    error.explained=true;
    if (['network','timeout'].includes(error.kind)) {
      try {
        const result=await request('/api/health',{}, {timeoutMs:3000});
        if (result.application!=='gaze-api-compare') throw new Error('Unexpected server');
        const op=result.last_operation;
        error.message+='\n서버 상태 확인: HTTP 서버는 응답합니다.';
        if (op) error.message+=` 마지막 처리: ${op.stage || '알 수 없음'}${op.engine ? ` / ${op.engine}` : ''} (${op.state || '알 수 없음'}, 프레임 ${op.frame_seq ?? '—'}). 모델 처리 상태이며 브라우저 수신 완료를 뜻하지 않습니다.`;
        error.message+=' 프레임 실패의 원인은 로그로 확인해야 합니다.';
      } catch {
        error.message+='\n서버 상태 확인 요청도 실패했습니다. Python 프로세스 종료·포트·연결 상태를 확인하세요. 원인은 아직 확정할 수 없습니다.';
      }
    }
    error.message+='\n자동 기록: 프로젝트의 logs/runtime.log, logs/last_operation.json, logs/native_fault.log. 강제 종료는 기록이 남지 않을 수 있습니다. 프레임 요청은 자동 재전송하지 않습니다.';
  }
  async function recoverFrame(error,{sessionId,seq,token}, {attempts=4,waitMs=250}={}) {
    if (!['network','timeout'].includes(error?.kind)
      || !/^[0-9a-f]{32}$/.test(sessionId || '') || !Number.isSafeInteger(seq) || seq<0) return null;
    for (let attempt=0;attempt<attempts;attempt++) {
      try {
        // Only retrieve this exact response. Never send the PNG or run a model
        // again. Query by frame number; credentials/session stay in headers.
        const result=await request(`/api/frame-result?seq=${seq}`,{headers:{'X-Gaze-Token':token,'X-Gaze-Session':sessionId}}, {timeoutMs:3000});
        if (result.pending===true) {
          if (result.seq!==seq) throw new Error('복구 중 프레임 번호 불일치');
        } else {
          if (result.session_id!==sessionId || result.seq!==seq || typeof result.accepted!=='boolean') {
            throw new Error('복구 응답의 세션 또는 프레임 번호가 다릅니다. 적용하지 않습니다.');
          }
          log(`프레임 ${seq} 응답 복구 완료 · 기존 처리 결과 사용 · 모델 재실행/추가 보정 없음`);
          return result;
        }
      } catch(recoveryError) {
        // An unknown frame may not have reached the server at all. Never
        // substitute the last available frame or invent its acceptance status.
        if (recoveryError.kind==='http' && recoveryError.status===404) {
          error.message+=`\n프레임 ${seq}의 저장된 응답이 없어 복구하지 못했습니다.`;
          return null;
        }
        if (!['network','timeout'].includes(recoveryError.kind)) {
          error.message+=`\n응답 복구 실패: ${recoveryError.message}`;
          return null;
        }
      }
      if (attempt+1<attempts) await new Promise(resolve=>setTimeout(resolve,waitMs));
    }
    error.message+=`\n프레임 ${seq} 응답 복구 대기 한도를 넘었습니다. POST는 재전송하지 않았습니다.`;
    return null;
  }
  async function diagnose() {
    const button=$('networkCheck');
    if (button) button.disabled=true;
    if ($('networkPanel')) $('networkPanel').open=true;
    log(`연결 진단 · ${new Date().toISOString()}\n페이지: ${displayURL(location.href)}\n카메라/모델을 실행하지 않습니다.`);
    try {
      const result=await health();
      log(`서버 연결 OK · ${result.revision}\n이 응답은 모델 작업 대기열을 거치지 않습니다.`);
      const queue=result.web_files.slice();
      let failures=0;
      // HEAD checks file availability without downloading or executing the model.
      await Promise.all(Array.from({length:4},async()=>{
        while (queue.length) {
          const file=queue.shift();
          try {
            await request(file.url,{method:'HEAD'},{head:true,expectedBytes:file.expected_bytes});
            log(`OK ${displayURL(file.url)}${file.expected_bytes===0 ? ' (원본 0-byte 정상 파일)' : ''}`);
          }
          catch(error) { failures++; log(error.message); }
        }
      }));
      log(failures ? `${failures}개 파일 요청 실패. 위 실패 주소와 F12 Network의 Request URL을 확인하세요.`
        : 'HTTP/파일 응답 정상. 모델 초기화·카메라 인식·추적 성공을 검증한 것은 아닙니다. 문제가 계속되면 F12 Network의 실패 Request URL과 Python traceback을 함께 확인하세요.');
    } catch(error) { report(error); }
    finally { if (button) button.disabled=false; }
  }
  window.gazeNetwork={request,assertAssets,diagnose,recoverFrame,explainFailure,report};
  window.addEventListener('error',event=>{
    const url=event.target?.src || event.target?.href;
    if (url) report(new RequestFailure('resource',url,'브라우저 리소스 로딩 실패. F12 → Network에서 이 주소의 상태를 확인하세요.'));
    else if (event.message) report(new Error(`${event.message}${event.filename ? `\n파일: ${displayURL(event.filename)}` : ''}`));
  },true);
  window.addEventListener('unhandledrejection',event=>report(event.reason));
  document.addEventListener('DOMContentLoaded',()=>{
    if ($('networkCheck')) $('networkCheck').onclick=diagnose;
    render();
    if (entries.length && $('networkPanel')) $('networkPanel').open=true;
    if (location.protocol!=='http:') report(new Error('run.py 실행 후 터미널에 표시된 http://127.0.0.1:포트/ 주소에 직접 접속하세요. HTML 파일을 직접 열면 동작하지 않습니다.'));
  });
})();
