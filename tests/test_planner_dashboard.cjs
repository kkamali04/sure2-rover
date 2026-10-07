// Real browser regressions for the public static planner; never opens hardware.
const {chromium}=require('playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
(async()=>{
 const server=http.createServer((req,res)=>{const url=req.url.split('?')[0],name=url==='/'?'index.html':url.slice(1),allowed=['index.html','debug.html','preview/vendor/three.min.js','preview/assets.js','preview/scene.js'];if(!allowed.includes(name)){res.writeHead(404);res.end();return;}res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':'text/html; charset=utf-8');res.end(fs.readFileSync(path.join(root,'github-pages',name)));});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 let browser;const passed=[],errors=[],api=[];
 try{
  browser=await chromium.launch({headless:true});const page=await browser.newPage({viewport:{width:1440,height:900}});
  page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.url().includes('/api/'))api.push(r.url());});
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  const plan=()=>page.evaluate(()=>window.PlannerUI.getPlan());
  const openSettings=async()=>{if(!(await page.locator('#settingsDialog').isVisible()))await page.locator('#settingsBtn').click();};
  const reset=async()=>{if(await page.locator('#stopBtn').isEnabled())await page.locator('#stopBtn').click();if(await page.locator('#settingsDialog').isVisible())await page.locator('#closeSettings').click();await page.locator('#editTab').click();await openSettings();await page.locator('#resetBtn').click();await page.locator('#closeSettings').click();await page.locator('#topTab').click();};
  const test=async(name,run)=>{await run();passed.push(name);console.log('PASS '+name);};
  await test('default 2 by 6 layout, three heights, 36 targets and real-time preview',async()=>{
   const p=await plan();assert.equal(p.stations.length,12);assert.equal(new Set(p.stations.map(s=>s.y_mm)).size,2);
   assert.deepEqual(p.heights_mm,[150,350,550]);assert.equal(await page.locator('#sampleCount').innerText(),'36');
   assert.equal(await page.locator('#simSpeed').inputValue(),'1');assert.equal(await page.locator('#handoffBtn').count(),0);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight),true,'desktop dashboard fits one viewport');
  });
  await test('half-length point waits are editable and survive JSON export/import',async()=>{
   await reset();let p=await plan();assert.equal(p.settle_s,2.5);assert(p.stations.every(s=>s.dwell_s===5));
   await page.locator('#timingBtn').click();await page.locator('#settle').fill('1.5');await page.locator('#defaultDwell').fill('4');await page.locator('#applyDwell').click();await page.locator('#closeTiming').click();
   p=await plan();assert.equal(p.settle_s,1.5);assert(p.stations.every(s=>s.dwell_s===4));assert.equal(await page.evaluate(()=>PlannerCore.stationaryTime(PlannerUI.getPlan())),198);
   await openSettings();const d=page.waitForEvent('download');await page.locator('#jsonBtn').click();const bytes=fs.readFileSync(await (await d).path());const saved=JSON.parse(bytes);assert.equal(saved.settle_s,1.5);assert(saved.stations.every(s=>s.dwell_s===4));await page.locator('#resetBtn').click();await page.locator('#importFile').setInputFiles({name:'timing.json',mimeType:'application/json',buffer:bytes});await page.waitForFunction(()=>PlannerUI.getPlan().settle_s===1.5);await page.locator('#closeSettings').click();await reset();
  });
  await test('pointer selection survives redraw and repeated 5 mm arrow nudges; Shift gives 1 mm',async()=>{
   await page.locator('#planSvg .station[data-id="S3"] circle').click();
   const start=(await plan()).stations[2];await page.keyboard.press('ArrowRight');await page.keyboard.press('ArrowRight');await page.keyboard.press('Shift+ArrowUp');
   const s=(await plan()).stations[2];assert.equal(s.x_mm,start.x_mm+10);assert.equal(s.y_mm,start.y_mm+1);
   assert.equal(await page.locator('#selectionTitle').innerText(),'Station S3');
   await page.keyboard.press('Delete');assert(!(await plan()).stations.some(s=>s.id==='S3'));
  });
  await test('whole footprint selects; side-panel Delete removes that station',async()=>{
   await reset();await page.locator('#planSvg rect[data-id="S8"]').click({position:{x:6,y:6}});
   assert.equal(await page.locator('#selectionTitle').innerText(),'Station S8');await openSettings();await page.locator('#deleteStation').click();await page.locator('#closeSettings').click();
   assert(!(await plan()).stations.some(s=>s.id==='S8'));
  });
  await test('right-click menu is small, above the station, nonmodal, dismissible and can delete',async()=>{
   await reset();const dot=page.locator('#planSvg .station[data-id="S4"] circle');await dot.click({button:'right'});
   const menu=await page.locator('#stationMenu').boundingBox(),target=await dot.boundingBox();
   assert(menu.width<200&&menu.height<120);assert(menu.y+menu.height<=target.y+target.height/2);
   assert.equal(await page.locator('dialog[open]').count(),0);assert(await page.locator('#stationDialog').isHidden());
   await page.screenshot({path:path.join(root,'browser-validation/dashboard-context-menu.png'),fullPage:false});
   await page.keyboard.press('Escape');assert(await page.locator('#stationMenu').isHidden());
   await dot.click({button:'right'});await page.locator('#stationCount').click();assert(await page.locator('#stationMenu').isHidden());
   await dot.click({button:'right'});await page.locator('#menuChange').click();
   const editor=await page.locator('#stationDialog').boundingBox();assert(editor.width<=340&&editor.height<390);
   assert.equal(await page.locator('dialog[open]').count(),0);await page.keyboard.press('Escape');assert(await page.locator('#stationDialog').isHidden());
   await dot.click({button:'right'});await page.keyboard.press('ArrowDown');await page.keyboard.press('ArrowDown');await page.keyboard.press('Enter');
   assert(!(await plan()).stations.some(s=>s.id==='S4'));assert(await page.locator('#stationMenu').isHidden());
  });
  await test('right-click edits exact mm/dwell values and preserves preview settings on JSON roundtrip',async()=>{
   await reset();await page.locator('#planSvg .station[data-id="S2"] circle').click({button:'right'});
   await page.locator('#menuChange').click();
   await page.locator('#contextX').fill('410');await page.locator('#contextY').fill('240');await page.locator('#contextDwell').fill('18');await page.locator('#applyContext').click();
   const s=(await plan()).stations[1];assert.equal(s.x_mm,410);assert.equal(s.y_mm,240);assert.equal(s.dwell_s,18);
   await openSettings();const download=page.waitForEvent('download');await page.locator('#jsonBtn').click();const file=await (await download).path();const data=JSON.parse(fs.readFileSync(file,'utf8'));
   assert.deepEqual(data.preview_timing,{lift_transition_s:20,rover_transition_s:3});assert.equal(data.derived.sample_count,36);
   await page.locator('#importFile').setInputFiles({name:'roundtrip.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(data))});
   await page.waitForFunction(()=>window.PlannerUI.getPlan().stations[1].dwell_s===18);await page.locator('#closeSettings').click();
  });
  await test('typing and Delete inside coordinate input do not delete a station',async()=>{
   await openSettings();const before=(await plan()).stations.length;await page.locator('#selectedX').focus();await page.keyboard.press('Control+A');await page.keyboard.press('Delete');
   assert.equal((await plan()).stations.length,before);await page.locator('#selectedX').fill('420');await page.locator('#selectedX').press('Tab');
   assert.equal((await plan()).stations[0].x_mm,420);await page.locator('#closeSettings').click();
  });
  await test('table input click selects its row without swallowing editing; row delete targets that row',async()=>{
   await reset();await openSettings();await page.locator('#tableBtn').click();
   const input=page.locator('#stationRows input[data-id="S9"][data-field="x_mm"]');await input.click();
   assert.equal(await page.locator('#selectionTitle').innerText(),'Station S9');await input.fill('820');await input.press('Tab');
   assert.equal((await plan()).stations.find(s=>s.id==='S9').x_mm,820);
   await page.getByRole('button',{name:'Delete S9',exact:true}).click();assert(!(await plan()).stations.some(s=>s.id==='S9'));
   await page.locator('#closeTable').click();await page.locator('#closeSettings').click();
  });
  await test('height view isolates selected station and probe dot focuses its Z input',async()=>{
   await reset();await page.locator('#frontTab').click();assert.equal(await page.locator('#frontSvg [data-height]').count(),3);
   await page.locator('#frontSvg [data-height="2"]').click();assert.equal(await page.locator('#z2').evaluate(n=>n===document.activeElement),true);
   await page.locator('#z2').fill('360');assert.equal((await plan()).heights_mm[1],360);await page.locator('#topTab').click();
  });
  await test('height dots drag vertically in mm, clamp to neighbours/envelope, release outside, and update 3D/export',async()=>{
   await reset();await page.locator('#frontTab').click();const stations=(await plan()).stations;
   const dragHeight=async(index,z,release=true)=>{const dot=page.locator('#frontSvg [data-height="'+index+'"]');const b=await dot.boundingBox();const end=await page.locator('#frontSvg').evaluate((svg,z)=>{const p=new DOMPoint(Number(svg.dataset.left),Number(svg.dataset.bottom)-z*Number(svg.dataset.scale)).matrixTransform(svg.getScreenCTM());return {x:p.x,y:p.y};},z);await page.mouse.move(b.x+b.width/2,b.y+b.height/2);await page.mouse.down();await page.mouse.move(b.x+b.width/2+20,end.y,{steps:8});if(release)await page.mouse.up();};
   await dragHeight(2,410);assert.equal((await plan()).heights_mm[1],410);assert.equal(await page.locator('#z2').inputValue(),'410');
   await dragHeight(2,320);assert.equal((await plan()).heights_mm[1],320);assert.deepEqual((await plan()).stations,stations);
   await dragHeight(2,600);assert.equal((await plan()).heights_mm[1],549);
   await dragHeight(2,100);assert.equal((await plan()).heights_mm[1],151);
   const bounds=await page.evaluate(()=>PlannerCore.limits(PlannerUI.getPlan()));await page.locator('#z1').focus();await dragHeight(1,0);assert.equal((await plan()).heights_mm[0],Math.ceil(bounds.zMin));
   await dragHeight(3,750);assert.equal((await plan()).heights_mm[2],Math.floor(bounds.zMax));
   await dragHeight(2,380,false);await page.mouse.move(5,5);await page.mouse.up();const released=(await plan()).heights_mm.slice();await page.mouse.move(600,600);assert.deepEqual((await plan()).heights_mm,released);
   await dragHeight(2,380);await page.locator('#previewTab').click();await page.waitForFunction(()=>CIQPreview.getState().ready);assert.equal(await page.evaluate(()=>CIQPreview.getState().plan.heights_mm[1]),380);
   await page.locator('#editTab').click();await openSettings();const d=page.waitForEvent('download');await page.locator('#jsonBtn').click();const saved=JSON.parse(fs.readFileSync(await (await d).path()));assert.equal(saved.heights_mm[1],380);assert(saved.derived.samples.filter(s=>s.height_index===2).every(s=>s.z_mm===380));await page.locator('#closeSettings').click();await reset();
  });
  await test('slow preview has distinct lift, park, settle and dwell phases and freezes edits',async()=>{
   await reset();const events=await page.evaluate(()=>window.PlannerUI.previewEvents());
   assert.equal(events.filter(e=>e.phase==='Lift transition (assumed)').length,24);assert.equal(events.filter(e=>e.phase==='Lift park (assumed)').length,12);
   assert(events.filter(e=>e.phase.includes('Lift')).every(e=>e.end-e.start===20));assert.equal(events.at(-1).end,1029);
   await page.locator('#previewBtn').click();assert(await page.locator('#selectedX').isDisabled());assert(await page.locator('#deleteStation').isDisabled());
   await page.locator('#stopBtn').click();assert(await page.locator('#selectedX').isEnabled());
  });
  await test('out-of-bounds exact edit is visible and blocks export rather than being silently clamped',async()=>{
   await page.locator('#editTab').click();await openSettings();await page.locator('#selectedX').fill('-5');await page.locator('#selectedX').press('Tab');assert.equal((await plan()).stations[0].x_mm,-5);
   assert(await page.locator('#jsonBtn').isDisabled());assert(await page.locator('#previewBtn').isDisabled());await page.locator('#closeSettings').click();await reset();
  });
  await test('S6 and S7 have two left 90-degree turns and mismatched fixed presets are rejected',async()=>{
   await reset();const r=await page.evaluate(()=>PlannerCore.route(PlannerUI.getPlan()));assert.equal(r[5].turn_deg,90);assert.equal(r[6].turn_deg,90);assert.equal(r[6].heading_deg,-180);
   assert.equal(await page.locator('#planSvg g[data-id="S6"][data-action]').getAttribute('data-action'),'Left 90°');
   await page.locator('#planSvg .station[data-id="S6"] circle').click({button:'right'});await page.locator('#menuDirection').click();await page.locator('#contextAction').selectOption('right90');await page.locator('#applyContext').click();assert(await page.locator('#previewBtn').isDisabled());assert((await page.locator('#routeHint').innerText()).includes('does not point'));
   await reset();
  });
  await test('backward preset keeps heading while traveling to a point behind it',async()=>{
   await page.evaluate(()=>{const p=PlannerUI.getPlan();p.stations=[{id:'S1',x_mm:600,y_mm:300,dwell_s:1,departure:'reverse'},{id:'S2',x_mm:400,y_mm:300,dwell_s:1}];PlannerUI.setPlan(p);});
   const r=await page.evaluate(()=>PlannerCore.route(PlannerUI.getPlan()));assert.equal(r[0].heading_deg,0);assert.equal(r[0].reverse,true);assert.equal(r[0].turn_deg,0);await reset();
  });
  await test('3D WebGL renders the shared plan and the original X Z Y coordinate transform',async()=>{
   await page.locator('#previewTab').click();await page.waitForFunction(()=>window.CIQPreview?.getState().ready);
   let state=await page.evaluate(()=>CIQPreview.getState());assert(state.frames>0);assert.equal(state.plan.stations.length,12);assert.equal(state.axis_map,'X,Z,Y (original preview)');assert(await page.locator('#previewError').isHidden());
   await page.evaluate(()=>CIQPreview.setPose({x:600,y:300,z:350,heading:90}));state=await page.evaluate(()=>CIQPreview.getState());assert.deepEqual(state.roverWorldPosition,[600,0,300]);assert.deepEqual(state.probeWorldPosition,[600,350,300]);
   await page.screenshot({path:path.join(root,'browser-validation/preview-3d.png'),fullPage:true});await page.locator('#editTab').click();
  });
  await test('camera presets remain freely orbitable and zoomable; cutaway is available',async()=>{
   await page.locator('#previewTab').click();
   for(const name of ['front','top','side','iso']){await page.locator('[data-view="'+(name==='iso'?'home':name)+'"]').click();assert.equal(await page.evaluate(()=>CIQPreview.getState().camera.mode),name);}
   const before=await page.evaluate(()=>CIQPreview.getState().camera);const box=await page.locator('#previewViewport').boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+60,box.y+box.height/2+30);await page.mouse.up();assert.equal(await page.evaluate(()=>CIQPreview.getState().camera.mode),'free');assert.notEqual(await page.evaluate(()=>CIQPreview.getState().camera.theta),before.theta);
   await page.mouse.wheel(0,200);await page.waitForTimeout(80);assert.notEqual(await page.evaluate(()=>CIQPreview.getState().camera.radius),before.radius);await page.locator('.component-menu summary').click();await page.locator('[data-layer="shell"]').uncheck();assert.equal(await page.evaluate(()=>CIQPreview.getState().camera.cutaway),true);await page.locator('[data-layer="shell"]').check();await page.locator('.component-menu summary').click();await page.locator('[data-view="home"]').click();await page.locator('#editTab').click();
  });
  await test('timeline scrubs to actual lift, travel and S6 turn poses; speed changes during playback',async()=>{
   await reset();const events=await page.evaluate(()=>PlannerUI.previewEvents());assert.equal(events[0].phase,'Settle');
   const total=events.at(-1).end;const seek=async(seconds)=>{await page.locator('#previewTimeline').evaluate((el,v)=>{el.value=String(v);el.dispatchEvent(new Event('input',{bubbles:true}));},seconds/total*1000);await page.waitForTimeout(80);};
   for(const phase of ['Lift transition (assumed)','Forward travel (assumed)','Left 90\u00b0 (preset preview)']){const event=events.find(e=>e.phase===phase);assert(event,phase);await seek((event.start+event.end)/2);const pose=await page.evaluate(()=>CIQPreview.getState().pose);const axis=phase.startsWith('Lift')?'z':phase.startsWith('Forward')?'x':'heading';assert(pose[axis]>Math.min(event.from[axis],event.to[axis])&&pose[axis]<Math.max(event.from[axis],event.to[axis]),phase+' must show interpolated motion');}
   await page.locator('#pauseBtn').click();await page.locator('#simSpeed').selectOption('60');assert.equal(await page.locator('#simSpeed').inputValue(),'60');await page.locator('#nextStationBtn').click();await page.locator('#stopBtn').click();await page.locator('#editTab').click();
  });
  await test('playback pauses without advancing and resets without physical commands',async()=>{
   await reset();await page.locator('#previewBtn').click();await page.waitForTimeout(200);await page.locator('#pauseBtn').click();await page.waitForTimeout(80);const a=await page.evaluate(()=>CIQPreview.getState().pose);await page.waitForTimeout(180);assert.deepEqual(await page.evaluate(()=>CIQPreview.getState().pose),a);await page.locator('#pauseBtn').click();await page.locator('#stopBtn').click();await page.locator('#editTab').click();
  });
  await test('complete 36-target preview reaches final pose; Reset returns to first station',async()=>{
   await reset();await page.evaluate(()=>{const p=PlannerUI.getPlan();p.settle_s=0;p.stations.forEach(s=>s.dwell_s=0);p.preview_timing={lift_transition_s:.1,rover_transition_s:.1};PlannerUI.setPlan(p);});
   await page.locator('#simSpeed').selectOption('10');await page.locator('#previewBtn').click();await page.waitForFunction(()=>document.getElementById('simStatus').textContent.includes('Preview complete'),null,{timeout:10000});
   const last=(await plan()).stations.at(-1),pose=await page.evaluate(()=>CIQPreview.getState().pose);assert.equal(pose.x,last.x_mm);assert.equal(pose.y,last.y_mm);assert.equal(pose.z,150);assert.equal(Math.abs(pose.heading),180);
   await page.locator('#previewBtn').click();await page.waitForTimeout(100);await page.locator('#stopBtn').click();const first=(await plan()).stations[0];const stopped=await page.evaluate(()=>CIQPreview.getState().pose);assert.deepEqual(stopped,{x:first.x_mm,y:first.y_mm,z:150,heading:0});await reset();
  });
  await test('idle Next station starts paused, timeline End reaches final time, and Reset restores Pause label',async()=>{
   await reset();await page.locator('#previewTab').click();assert(await page.locator('#nextStationBtn').isEnabled());await page.locator('#nextStationBtn').click();await page.waitForFunction(()=>document.getElementById('simStatus').textContent.includes('S2'));
   assert.equal(await page.locator('#pauseBtn').innerText(),'Resume');await page.locator('#previewTimeline').focus();await page.keyboard.press('End');await page.waitForFunction(()=>document.getElementById('simStatus').textContent.includes('Preview complete'));assert.equal(await page.locator('#previewClock').innerText(),'17:09 / 17:09');assert(await page.locator('#stopBtn').isEnabled());await page.locator('#stopBtn').click();assert.equal(await page.locator('#previewClock').innerText(),'0:00');assert.equal(await page.locator('#pauseBtn').innerText(),'Pause');
   await page.locator('#previewBtn').click();await page.locator('#pauseBtn').click();await page.locator('#stopBtn').click();assert.equal(await page.locator('#pauseBtn').innerText(),'Pause');await page.locator('#editTab').click();
  });
  await test('compact homepage hides settings and imports; debug tab opens the remote UI directly',async()=>{
   assert(await page.locator('#jsonBtn').isHidden());assert(await page.locator('#importBtn').isHidden());assert.equal(await page.locator('.metrics').count(),0);assert.equal(await page.locator('.footerbar').count(),0);
   await page.locator('#debugTab').click();assert.equal(await page.locator('#armState').innerText(),'DISARMED');assert(await page.locator('#forward').isDisabled());assert.equal(await page.locator('script[src]').count(),0);await page.goBack();
  });
  await page.screenshot({path:path.join(root,'browser-validation/dashboard-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await test('mobile layout has no horizontal page overflow',async()=>assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true));
  await page.screenshot({path:path.join(root,'browser-validation/dashboard-mobile.png'),fullPage:true});
  await test('offline file opens and renders 3D without a server',async()=>{const folder=fs.mkdtempSync(path.join(root,'browser-validation/standalone-'));const file=path.join(folder,'planner.html');fs.copyFileSync(path.join(root,'github-pages/index.html'),file);await page.goto(require('node:url').pathToFileURL(file).href);await page.locator('#previewTab').click();await page.waitForFunction(()=>CIQPreview.getState().ready);assert(await page.locator('#previewError').isHidden());});
  assert.deepEqual(errors,[]);assert.deepEqual(api,[]);
  fs.writeFileSync(path.join(root,'browser-validation/dashboard-results.json'),JSON.stringify({time:new Date().toISOString(),passed,errors,apiRequests:api,scope:'Static browser planning only; no hardware'},null,2));
 }finally{if(browser)await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
