// No browser/server/camera: execute the diagnostic helper with a fake fetch.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

const source=await readFile(new URL('../web/diagnostics.js',import.meta.url),'utf8');
function harness(fetch,{href='http://127.0.0.1:8765/'}={}) {
  const events=new Map();
  const nodes=new Map(['networkLog','networkPanel','networkCheck','message'].map(key=>[key,{}]));
  const window={addEventListener:(key,fn)=>events.set(key,fn)};
  const document={getElementById:key=>nodes.get(key),addEventListener:(key,fn)=>events.set(key,fn)};
  const context={window,document,location:new URL(href),URL,AbortController,setTimeout,clearTimeout,fetch};
  vm.runInNewContext(source,context);
  return {...window.gazeNetwork,nodes,events};
}
const response=(body,status=200)=>({ok:status>=200 && status<300,status,
  headers:new Headers({'Content-Length':'100'}),json:async()=>body});

test('HTTP model exception retains status, exact path, and original logger error',async()=>{
  let calls=0;
  const app=harness(async()=>{calls++; return response({error:'Exception: Logger has not been initialized.'},500);});
  await assert.rejects(app.request('/api/finish',{method:'POST'}),error=>
    error.kind==='http' && error.message.includes('Logger has not been initialized.')
    && error.message.includes('500') && error.url==='http://127.0.0.1:8765/api/finish');
  assert.equal(calls,1);
});

test('timeout aborts a pending POST once and explicitly says server work may continue',async()=>{
  let calls=0,aborted=false;
  const app=harness((_url,options)=>new Promise((_resolve,reject)=>{
    calls++;
    options.signal.addEventListener('abort',()=>{aborted=true; reject(new DOMException('aborted','AbortError'));});
  }));
  await assert.rejects(app.request('/api/frame',{method:'POST',body:'private frame'},{timeoutMs:10}),error=>
    error.kind==='timeout' && error.url.endsWith('/api/frame')
    && error.message.includes('계속 진행 중') && !error.message.includes('private frame'));
  assert.equal(calls,1); assert.equal(aborted,true);
});

test('timeout also bounds an unfinished response body',async()=>{
  const app=harness(async(_url,options)=>({ok:true,status:200,
    json:()=>new Promise((_resolve,reject)=>options.signal.addEventListener('abort',()=>reject(new DOMException('aborted','AbortError'))))}));
  await assert.rejects(app.request('/api/config',{}, {timeoutMs:10}),error=>error.kind==='timeout');
});

test('network failure, missing file, and wrong JSON response remain distinct',async()=>{
  const failed=harness(async()=>{throw new TypeError('Failed to fetch');});
  await assert.rejects(failed.request('/api/config'),error=>error.kind==='network' && error.url.endsWith('/api/config'));
  const missing=harness(async()=>response({},404));
  await assert.rejects(missing.request('/mediapipe/face_mesh/face_mesh.binarypb',{method:'HEAD'},{head:true}),error=>error.kind==='http' && error.message.includes('404'));
  const wrong=harness(async()=>({ok:true,status:200,json:async()=>{throw new SyntaxError('HTML');}}));
  await assert.rejects(wrong.request('/api/config'),error=>error.kind==='json');
});

test('manual diagnosis reads only health and HEAD files; missing file is shown',async()=>{
  const calls=[];
  const app=harness(async(url,options)=>{
    calls.push([new URL(url).pathname,options.method || 'GET']);
    if (url.endsWith('/api/health')) return response({application:'gaze-api-compare',revision:'test',
      web_files:[{url:'/vendor/webgazer.js',exists:true,bytes:123},{url:'/mediapipe/face_mesh/missing.wasm',exists:false,bytes:0}]});
    return response(null,url.endsWith('missing.wasm')?404:200);
  });
  await app.diagnose();
  assert.deepEqual(calls,[['/api/health','GET'],['/vendor/webgazer.js','HEAD'],['/mediapipe/face_mesh/missing.wasm','HEAD']]);
  assert.match(app.nodes.get('networkLog').textContent,/missing.wasm/);
  assert.match(app.nodes.get('networkLog').textContent,/1개 파일 요청 실패/);
  assert.equal(app.nodes.get('networkCheck').disabled,false);
});

test('resource failure is recorded before DOM exists and strips URL query credentials',()=>{
  const app=harness(async()=>response({}));
  const logNode=app.nodes.get('networkLog');
  app.nodes.delete('networkLog');
  app.events.get('error')({target:{src:'https://example.com/model.js?token=secret'}});
  app.nodes.set('networkLog',logNode);
  app.events.get('DOMContentLoaded')();
  assert.match(logNode.textContent,/https:\/\/example.com\/model.js/);
  assert.doesNotMatch(logNode.textContent,/secret/);
  assert.equal(app.nodes.get('networkPanel').open,true);
});

test('file pages and cross-origin probes never make a request',async()=>{
  let calls=0;
  const fake=async()=>{calls++; return response({});};
  const file=harness(fake,{href:'file:///tmp/web/index.html'});
  await assert.rejects(file.request('/api/config'),/index.html/);
  const external=harness(fake);
  await assert.rejects(external.request('https://example.com/model'),/외부 요청/);
  assert.equal(calls,0);
});

test('preflight identifies missing local files without starting a model',async()=>{
  const calls=[];
  const app=harness(async(url,options)=>{
    calls.push([url,options.method || 'GET']);
    return response({application:'gaze-api-compare',revision:'test',web_files:[{url:'/vendor/webgazer.js',exists:false,bytes:0}]});
  });
  await assert.rejects(app.assertAssets(),/python setup_envs.py --only webgazer/);
  assert.equal(calls.length,1); assert.equal(calls[0][1],'GET');
});

test('original zero-byte MediaPipe data passes preflight and HEAD diagnosis',async()=>{
  const path='/mediapipe/face_mesh/face_mesh_solution_simd_wasm_bin.data';
  const app=harness(async(url)=>{
    if (url.endsWith('/api/health')) return response({application:'gaze-api-compare',revision:'test',
      web_files:[{url:path,exists:true,bytes:0,expected_bytes:0}]});
    return {...response(null),headers:new Headers({'Content-Length':'0'})};
  });
  await app.assertAssets();
  await app.diagnose();
  assert.match(app.nodes.get('networkLog').textContent,/원본 0-byte 정상 파일/);
  assert.match(app.nodes.get('networkLog').textContent,/HTTP\/파일 응답 정상/);
});

test('zero-byte WASM with nonzero expected size is still rejected',async()=>{
  const path='/mediapipe/face_mesh/face_mesh_solution_simd_wasm_bin.wasm';
  const app=harness(async(url)=>{
    if (url.endsWith('/api/health')) return response({application:'gaze-api-compare',revision:'test',
      web_files:[{url:path,exists:true,bytes:0,expected_bytes:6161697}]});
    return {...response(null),headers:new Headers({'Content-Length':'0'})};
  });
  await assert.rejects(app.assertAssets(),/원본 크기와 다릅니다/);
  await assert.rejects(app.request(path,{method:'HEAD'},{head:true,expectedBytes:6161697}),error=>error.kind==='size');
});

test('failed frame performs exactly one read-only probe, with no POST retry',async()=>{
  const calls=[];
  const app=harness(async(url,options)=>{
    const path=new URL(url).pathname;
    calls.push([path,options.method || 'GET']);
    if (path==='/api/frame') throw new TypeError('Failed to fetch');
    return response({application:'gaze-api-compare',last_operation:{state:'busy',stage:'engine.process',engine:'gazefollower'}});
  });
  let failure;
  try { await app.request('/api/frame',{method:'POST',body:'private image'}); }
  catch(error) { failure=error; }
  await app.explainFailure(failure);
  await app.explainFailure(failure);
  assert.deepEqual(calls,[['/api/frame','POST'],['/api/health','GET']]);
  assert.match(failure.message,/HTTP 서버는 응답합니다/);
  assert.match(failure.message,/engine.process \/ gazefollower/);
  assert.match(failure.message,/native_fault.log/);
  assert.doesNotMatch(failure.message,/private image/);
});

test('unreachable health reports uncertainty, never claims a model caused the error',async()=>{
  let calls=0;
  const app=harness(async()=>{calls++; throw new TypeError('Failed to fetch');});
  const failure=Object.assign(new Error('frame failed'),{kind:'network'});
  await app.explainFailure(failure);
  assert.equal(calls,1);
  assert.match(failure.message,/원인은 아직 확정할 수 없습니다/);
  assert.match(failure.message,/last_operation.json/);
});

test('HTTP exception retains actual message and adds logs without another request',async()=>{
  let calls=0;
  const app=harness(async()=>{calls++; return response({});});
  const failure=Object.assign(new Error('HTTP 500 · synthetic model error'),{kind:'http'});
  await app.explainFailure(failure);
  assert.equal(calls,0);
  assert.match(failure.message,/HTTP 500 · synthetic model error/);
  assert.match(failure.message,/runtime.log/);
});

const recoverySession='a'.repeat(32);
const recoveryOptions={sessionId:recoverySession,seq:55,token:'private-token'};
const completedFrame={session_id:recoverySession,seq:55,accepted:true,accepted_count:56,point_index:1,counts:[30,26,0,0,0,0,0,0,0]};

test('lost frame POST recovers exact completed JSON using GET only',async()=>{
  const calls=[];
  const app=harness(async(url,options)=>{
    calls.push([new URL(url).pathname,options.method || 'GET',options.body]);
    if (url.endsWith('/api/frame')) throw new TypeError('Failed to fetch');
    assert.equal(new URL(url).search,'?seq=55');
    assert.equal(options.headers['X-Gaze-Session'],recoverySession);
    assert.equal(options.headers['X-Gaze-Token'],'private-token');
    return response(completedFrame);
  });
  let error;
  try { await app.request('/api/frame',{method:'POST',body:'private-image'}); } catch(e) {error=e;}
  const recovered=await app.recoverFrame(error,recoveryOptions);
  assert.deepEqual(recovered,completedFrame);
  assert.deepEqual(calls,[['/api/frame','POST','private-image'],['/api/frame-result','GET',undefined]]);
  assert.match(app.nodes.get('message').textContent,/응답 복구 완료/);
  assert.doesNotMatch(app.nodes.get('message').textContent,/private/);
});

test('failed body read retains received HTTP status and is recoverable',async()=>{
  let calls=0;
  const app=harness(async()=>{
    calls++;
    if (calls===1) return {ok:true,status:200,json:async()=>{throw new TypeError('body stream disconnected');}};
    return response(completedFrame);
  });
  let error;
  try { await app.request('/api/frame',{method:'POST'}); } catch(e) {error=e;}
  assert.equal(error.kind,'network');
  assert.equal(error.stage,'response_body');
  assert.equal(error.status,200);
  assert.match(error.message,/응답 본문/);
  assert.deepEqual(await app.recoverFrame(error,recoveryOptions),completedFrame);
});

test('pending frame waits for that frame, never substitutes another response',async()=>{
  let calls=0;
  const app=harness(async()=>response(++calls===1 ? {pending:true,seq:55} : completedFrame,calls===1?202:200));
  const error=Object.assign(new Error('network lost'),{kind:'network'});
  assert.deepEqual(await app.recoverFrame(error,recoveryOptions,{waitMs:0}),completedFrame);
  assert.equal(calls,2);
});

test('missing reply stops recovery without another POST or an accepted sample',async()=>{
  let calls=0;
  const app=harness(async(_url,options)=>{calls++; assert.notEqual(options.method,'POST');return response({error:'No reply'},404);});
  const error=Object.assign(new Error('network lost'),{kind:'network'});
  assert.equal(await app.recoverFrame(error,recoveryOptions),null);
  assert.equal(calls,1);
  assert.match(error.message,/55.*저장된 응답이 없어/);
});

test('different session, different sequence, or absent acceptance flag is rejected',async()=>{
  for (const invalid of [{...completedFrame,session_id:'b'.repeat(32)}, {...completedFrame,seq:54}, {...completedFrame,accepted:undefined}]) {
    const app=harness(async()=>response(invalid));
    const error=Object.assign(new Error('network lost'),{kind:'network'});
    assert.equal(await app.recoverFrame(error,recoveryOptions),null);
    assert.match(error.message,/적용하지 않습니다/);
  }
});

test('real HTTP model error is not retried and cached errors remain errors',async()=>{
  let calls=0;
  const app=harness(async()=>{calls++;return response({error:'synthetic fitting exception'},500);});
  assert.equal(await app.recoverFrame(Object.assign(new Error('HTTP500'),{kind:'http'}),recoveryOptions),null);
  assert.equal(calls,0);
  const error=Object.assign(new Error('network lost'),{kind:'network'});
  assert.equal(await app.recoverFrame(error,recoveryOptions),null);
  assert.match(error.message,/synthetic fitting exception/);
  assert.equal(calls,1);
});

test('recovery is bounded and rejected calibration frames stay rejected',async()=>{
  let calls=0;
  const app=harness(async()=>{calls++;return response({pending:true,seq:55},202);});
  const error=Object.assign(new Error('network lost'),{kind:'timeout'});
  assert.equal(await app.recoverFrame(error,recoveryOptions,{attempts:2,waitMs:0}),null);
  assert.equal(calls,2);
  assert.match(error.message,/대기 한도/);
  const rejected=harness(async()=>response({...completedFrame,accepted:false,accepted_count:55}));
  const result=await rejected.recoverFrame(Object.assign(new Error('network lost'),{kind:'network'}),recoveryOptions);
  assert.equal(result.accepted,false);
  assert.equal(result.accepted_count,55);
});
