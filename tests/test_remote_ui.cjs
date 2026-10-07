// Mock-DOM/fake-fetch event tests. This does not verify real browser rendering.
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const html=fs.readFileSync(path.join(__dirname,'..','remote_controller.html'),'utf8');
const script=html.split('<script>')[1].split('</script>')[0];
const nodes={},documentEvents={},windowEvents={},intervals=[];
for(const m of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)) nodes[m[2]]={id:m[2],tagName:m[1].toUpperCase(),value:m[0].match(/value="([^"]*)"/)?.[1]||'',disabled:false,listeners:{},classList:{toggle(){},remove(){},add(){}},addEventListener(k,f){this.listeners[k]=f;},setPointerCapture(){},closest(){return null;}};
let backend={token:'fake-session-token-for-tests',seq:0,live:false,armed:false,pwm_cap:.25,deadman_ms:350,transport_state:'simulated',neutral_pending:false,age_ms:0,error:'',last_command:{T:1,L:0,R:0}};
const calls=[];let deferStop=false,pendingStop=null;
const snapshot=()=>JSON.parse(JSON.stringify(backend));
function response(data,ok=true){return {ok,status:ok?200:409,json:async()=>data};}
function processCall(url,init){
 if(!init.body)return response(snapshot());
 const p=JSON.parse(init.body); if(p.seq<=backend.seq)return response({...snapshot(),error:'Stale sequence'},false);
 backend.seq=p.seq;
 if(url.endsWith('/arm'))backend.armed=true;
 if(url.endsWith('/stop')||url.endsWith('/disarm')){backend.armed=false;backend.last_command={T:1,L:0,R:0};}
 if(url.endsWith('/drive'))backend.last_command={T:1,L:p.left,R:p.right};
 return response(snapshot());
}
const document={hidden:false,getElementById:id=>{assert.ok(nodes[id],'Missing '+id);return nodes[id];},addEventListener:(k,f)=>{documentEvents[k]=f;}};
const window={addEventListener:(k,f)=>{windowEvents[k]=f;}};
const ctx={window,document,location:{protocol:'http:',hostname:'127.0.0.1',origin:'http://127.0.0.1:8765'},performance:{now:()=>100},setTimeout,clearTimeout,setInterval:(f,ms)=>{intervals.push({f,ms});return intervals.length;},clearInterval(){},AbortController,console,
 fetch:async(url,init)=>{calls.push({url,body:init.body?JSON.parse(init.body):null});if(deferStop&&url==='/api/stop'){return new Promise(resolve=>{pendingStop=()=>{resolve(processCall(url,init));pendingStop=null;};});}return processCall(url,init);}};
vm.createContext(ctx);vm.runInContext(script,ctx);
const ui=window.RemoteControllerUI,core=window.RemoteControlCore;
const flush=async()=>{for(let i=0;i<15;i++)await new Promise(setImmediate);};
let passed=0;async function test(name,f){await f();passed++;console.log('PASS '+name);}
function event(code,target=nodes.forward){return {code,target,repeat:false,ctrlKey:false,altKey:false,metaKey:false,preventDefault(){}};}
(async()=>{
 await flush();
 await test('bootstrap explicitly stops and remains disarmed',async()=>{assert.equal(ui.getState().armed,false);assert.ok(calls.some(c=>c.url==='/api/stop'));assert.equal(ui.getState().live,false);});
 await test('PWM interpretation and editing filters are correct',async()=>{assert.equal(core.dutyPercent(.10),20);assert.equal(core.demand('forward',.1).left,.1);assert.equal(core.demand('left',.1).left,-.1);assert.throws(()=>core.demand('forward',NaN));assert.equal(core.isEditing(nodes.pwmSlider),true);await ui.arm();const n=calls.length;documentEvents.keydown(event('KeyW',nodes.pwmSlider));await flush();assert.equal(calls.length,n);assert.equal(ui.getState().hold,null);});
 await test('keyboard hold and release produce motion then neutral',async()=>{documentEvents.keydown(event('KeyW'));await flush();assert.equal(backend.last_command.L,.1);documentEvents.keyup(event('KeyW'));await flush();assert.equal(backend.last_command.L,0);assert.equal(ui.getState().armed,true);});
 await test('window blur and hidden tab stop and disarm',async()=>{ui.beginHold('forward','keyboard','KeyW');await flush();windowEvents.blur();await flush();assert.equal(ui.getState().armed,false);assert.equal(backend.last_command.L,0);await ui.arm();ui.beginHold('forward','keyboard','KeyW');await flush();document.hidden=true;documentEvents.visibilitychange();await flush();assert.equal(ui.getState().armed,false);assert.equal(backend.armed,false);document.hidden=false;});
 await test('pending STOP and stale status cannot enable rearm',async()=>{await ui.arm();ui.beginHold('forward','keyboard','KeyW');await flush();deferStop=true;const stop=ui.stop('Race test STOP');assert.equal(nodes.armButton.disabled,true);const arms=calls.filter(c=>c.url==='/api/arm').length;await ui.poll();assert.equal(nodes.armButton.disabled,true,'Stale poll reopened ARM');await ui.arm();assert.equal(calls.filter(c=>c.url==='/api/arm').length,arms);assert.ok(pendingStop);deferStop=false;pendingStop();await stop;await flush();assert.equal(ui.getState().armed,false);assert.equal(backend.last_command.L,0);});
 await test('mixed low-level hold sources stop instead of taking over',async()=>{await ui.arm();assert.equal(ui.beginHold('forward','keyboard','KeyW'),true);await flush();assert.equal(ui.beginHold('left','keyboard','KeyA'),false);await flush();assert.equal(ui.getState().armed,false);assert.equal(backend.last_command.L,0);});
 await test('keyboard combinations mix steering and preserve remaining keys',async()=>{await ui.arm();documentEvents.keydown(event('KeyW'));await flush();documentEvents.keydown(event('KeyD'));await flush();assert.equal(backend.last_command.L,.1);assert.equal(backend.last_command.R,.05);documentEvents.keyup(event('KeyD'));await flush();assert.equal(backend.last_command.L,.1);assert.equal(backend.last_command.R,.1);documentEvents.keyup(event('KeyW'));await flush();assert.equal(backend.last_command.L,0);assert.equal(ui.getState().armed,true);});
 await test('opposing direction keys stop and do not restart on release',async()=>{documentEvents.keydown(event('KeyA'));await flush();documentEvents.keydown(event('KeyD'));await flush();assert.equal(ui.getState().armed,false);assert.equal(backend.last_command.L,0);documentEvents.keyup(event('KeyD'));documentEvents.keyup(event('KeyA'));await flush();assert.equal(backend.last_command.L,0);});
 await test('status polling never arms the UI automatically',async()=>{backend.armed=true;await ui.poll();await flush();assert.equal(ui.getState().armed,false);assert.equal(backend.armed,false);});
 ui.dispose();await flush();
 console.log(`${passed} remote UI checks passed; fake DOM/fetch only, no rover or browser.`);
})().catch(e=>{console.error(e);process.exitCode=1;});
