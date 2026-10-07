// Real-browser checks against a private simulator. Never attaches to live control.
// Requires local Playwright and its Chromium browser (playwright install chromium).
'use strict';
const { chromium } = require('playwright');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'browser-validation');
fs.mkdirSync(output, { recursive: true });
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(check, label) {
  const end = Date.now() + 6000;
  while (Date.now() < end) {
    if (await check()) return;
    await delay(40);
  }
  throw Error('Timed out: ' + label);
}
(async () => {
  const reservation = net.createServer();
  await new Promise(resolve => reservation.listen(0, '127.0.0.1', resolve));
  const port = reservation.address().port;
  await new Promise(resolve => reservation.close(resolve));
  const url = `http://127.0.0.1:${port}`;
  const terminal = fs.createWriteStream(path.join(output, 'terminal.log'));
  const server = spawn(process.env.ROVER_TEST_PYTHON || 'python', [
    '-u', 'remote_controller.py', '--simulate', '--port', String(port),
    '--log', path.join(output, 'controller_log.jsonl'),
  ], { cwd: root, windowsHide: true });
  server.stdout.pipe(terminal, { end: false });
  server.stderr.pipe(terminal, { end: false });
  let startupError;
  server.on('error', error => { startupError = error; });
  const state = async () => {
    const response = await fetch(url + '/api/status');
    assert.equal(response.status, 200);
    const data = await response.json();
    assert.equal(data.live, false, 'Browser tests require simulation');
    return data;
  };
  let browser, page;
  const results = [], errors = [];
  let expectedNetworkFailure=false,expectedCalibrationRejections=0;
  try {
    await until(async () => {
      if (startupError) throw startupError;
      if (server.exitCode !== null) throw Error('Simulator exited: ' + server.exitCode);
      try { return !(await state()).neutral_pending; } catch { return false; }
    }, 'simulator startup');
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
    page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if(message.type()==='error'&&expectedCalibrationRejections&&message.text().includes('422')){expectedCalibrationRejections--;return;}if (message.type() === 'error'&&!expectedNetworkFailure) errors.push(message.text()); });
    await page.goto(url+'/debug');
    const ready = () => until(() => page.locator('#armButton').isEnabled(), 'ARM available');
    const arm = async () => {
      await ready();
      await page.locator('#armButton').click();
      await until(async () => {
        const ui = await page.evaluate(() => window.RemoteControllerUI.getState());
        return (await state()).armed && ui.armed && !ui.arming;
      }, 'armed and acknowledged in browser');
    };
    const demand = async (left, right, armed = true) => until(async () => {
      const s = await state();
      const ui = await page.evaluate(() => window.RemoteControllerUI.getState());
      return s.armed === armed && !s.neutral_pending && s.last_command.L === left && s.last_command.R === right
        && ui.armed === armed && !ui.neutralPending && (left || right || !ui.driveFlight);
    }, `command ${left}, ${right}; armed=${armed}`);
    const test = async (name, action) => {
      await action(); results.push(name); console.log('PASS ' + name);
    };
    await test('page loads disarmed in simulation with default PWM', async () => {
      await ready(); await demand(0, 0, false);
      assert.equal(await page.locator('#modeBadge').innerText(), 'SIMULATED TRANSPORT');
      assert.equal(await page.locator('#pwmValue').innerText(), '0.10');
      assert.equal(await page.locator('#forward').isDisabled(), true);
    });
    await arm();
    for (const [key, left, right] of [['w', .1, .1], ['s', -.1, -.1], ['a', -.1, .1], ['d', .1, -.1]]) {
      await test(key + ' hold reaches simulator; release sends neutral and stays armed', async () => {
        await page.keyboard.down(key); await demand(left, right);
        await page.keyboard.up(key); await demand(0, 0);
      });
    }
    for (const [travel, turn, left, right] of [['w','a',.05,.1],['w','d',.1,.05],['s','a',-.1,-.05],['s','d',-.05,-.1]]) {
      await test(travel+'+'+turn+' steering and partial releases', async () => {
        await page.keyboard.down(travel); await demand(travel==='w'?.1:-.1,travel==='w'?.1:-.1);
        await page.keyboard.down(turn); await demand(left,right);
        await page.keyboard.up(turn); await demand(travel==='w'?.1:-.1,travel==='w'?.1:-.1);
        await page.keyboard.up(travel); await demand(0,0);
        await page.keyboard.down(turn); await demand(turn==='a'?-.1:.1,turn==='a'?.1:-.1);
        await page.keyboard.down(travel); await demand(left,right);
        await page.keyboard.up(travel); await demand(turn==='a'?-.1:.1,turn==='a'?.1:-.1);
        await page.keyboard.up(turn); await demand(0,0);
      });
    }
    await test('pointer capture releases outside the direction button', async () => {
      const box = await page.locator('#forward').boundingBox();
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
      await page.mouse.down(); await demand(.1, .1);
      await page.mouse.move(10, 10); await page.mouse.up(); await demand(0, 0);
    });
    for (const key of ['Space', 'Escape']) {
      await test(key + ' stops and disarms', async () => {
        if (!(await state()).armed) await arm();
        await page.keyboard.down('w'); await demand(.1, .1);
        await page.keyboard.press(key); await demand(0, 0, false);
        await page.keyboard.up('w');
      });
    }
    await test('STOP button stops and disarms', async () => {
      await arm(); await page.keyboard.down('w'); await demand(.1, .1);
      await page.locator('#stopButton').click(); await demand(0, 0, false);
      await page.keyboard.up('w');
    });
    await test('opposing directions stop and disarm', async () => {
      await arm(); await page.keyboard.down('w'); await demand(.1, .1);
      await page.keyboard.down('s'); await demand(0, 0, false);
      await page.keyboard.up('w'); await page.keyboard.up('s');
    });
    await test('direction keys do not drive while PWM slider has focus', async () => {
      await arm(); await page.locator('#pwmSlider').focus();
      const seq = (await state()).seq;
      await page.keyboard.press('w'); await delay(200);
      assert.equal((await state()).seq, seq); await demand(0, 0);
      await page.keyboard.press('Escape'); await demand(0, 0, false);
    });
    await test('browser blur event stops and disarms (event injected in headless mode)', async () => {
      await arm(); await page.keyboard.down('w'); await demand(.1,.1);
      await page.evaluate(()=>window.dispatchEvent(new Event('blur')));
      await demand(0,0,false); await page.keyboard.up('w');
    });
    await test('PWM adjustment changes demand and release returns neutral',async()=>{
      await page.locator('#pwmSlider').fill('0.15');
      await arm();await page.locator('h1').click();
      await page.keyboard.down('w');await demand(.15,.15);
      assert.equal(await page.locator('#pwmSlider').isDisabled(),true);
      await page.keyboard.up('w');await demand(0,0);
      await page.locator('#stopButton').click();await demand(0,0,false);
      await page.locator('#pwmSlider').fill('0.1');
    });
    await test('lost browser link expires movement; reconnect stays stopped until explicit rearm',async()=>{
      await arm();await page.keyboard.down('w');await demand(.1,.1);
      expectedNetworkFailure=true;
      await page.route('**/api/**',route=>route.abort());
      await until(async()=>!(await state()).armed,'bridge heartbeat expiration');
      await page.keyboard.up('w');
      await page.unroute('**/api/**');
      await page.locator('#reconnectButton').click();await demand(0,0,false);
      await delay(200);expectedNetworkFailure=false;
      await page.keyboard.press('w');await demand(0,0,false);
      await arm();await page.keyboard.down('w');await demand(.1,.1);
      await page.keyboard.up('w');await demand(0,0);
      await page.locator('#stopButton').click();await demand(0,0,false);
    });
    await test('stopped-state telemetry button completes in simulation without invented fields',async()=>{
      await page.locator('#readTelemetry').click();
      await until(async()=>!(await state()).telemetry_busy,'telemetry queue completed');
      await demand(0,0,false);
      assert.ok((await state()).telemetry.fields.every(f=>f.value===null));
      assert.ok((await page.locator('#lastStopReason').innerText()).length>0);
    });
    await test('operator observations save to the session on disk', async () => {
      await page.locator('#checkName').selectOption({label:'Left pivot (A alone)'});
      await page.locator('#checkResult').selectOption('not_tested');
      await page.locator('#checkNotes').fill('Browser simulation only; physical pivot not tested.');
      await page.locator('#saveObservation').click();
      await until(async () => (await (await fetch(url+'/api/validation')).json()).observations.length===1, 'saved observation');
    });
    await test('calibration trials persist and export a non-executing route draft and raw-session ZIP',async()=>{
      let driveRequests=0;const watch=r=>{if(r.url().endsWith('/api/drive'))driveRequests++;};page.on('request',watch);
      await page.locator('#testPlanFile').setInputFiles(path.join(root,'example_plan_2x6.json'));
      await until(async()=> (await (await fetch(url+'/api/validation')).json()).plan?.stations.length===12,'loaded draft plan');
      await page.locator('#calibrationDraft summary').click();
      for(const [id,value] of [['calPWM','0.10'],['calSurface','software test floor'],['calConfiguration','synthetic fixture'],['calDuration','1'],['calNotes','Software example only; no rover measured']])await page.locator('#'+id).fill(value);
      expectedCalibrationRejections=1;const missing=page.waitForResponse(r=>r.url().endsWith('/api/validation')&&r.request().method()==='POST');await page.locator('#compileDraft').click();assert.equal((await missing).status(),422);await until(()=>expectedCalibrationRejections===0,'expected missing-calibration rejection');
      for(const direction of ['forward','left']){
        await page.locator('#calDirection').selectOption(direction);await page.locator('#calDisplacement').fill(direction==='forward'?'100':'90');
        for(let i=0;i<3;i++){const response=page.waitForResponse(r=>r.url().endsWith('/api/validation')&&r.request().method()==='POST');await page.locator('#saveCalibration').click();assert.equal((await response).status(),200);await until(async()=>!(await page.locator('#validationMessage').innerText()).startsWith('Not saved'),'trial saved');}
      }
      const compiled=page.waitForResponse(r=>r.url().endsWith('/api/validation')&&r.request().method()==='POST');await page.locator('#compileDraft').click();assert.equal((await compiled).status(),200);
      await until(async()=>await page.locator('#downloadDraft').isEnabled(),'draft ready');
      const download=page.waitForEvent('download');await page.locator('#downloadDraft').click();const draft=JSON.parse(fs.readFileSync(await (await download).path(),'utf8'));
      assert.equal(draft.hardware_execution_enabled,false);assert.equal(draft.calibration_trials.length,6);assert.equal(draft.measured_position,null);
      assert.equal(draft.steps.filter(s=>s.kind==='estimated_motion').length,13);
      const zipDownload=page.waitForEvent('download');await page.locator('#downloadSession').click();const zip=fs.readFileSync(await (await zipDownload).path());assert.equal(zip.subarray(0,2).toString(),'PK');
      const persisted=await(await fetch(url+'/api/validation')).json();assert.equal(persisted.calibration_trials.length,6);assert(persisted.saved_to);
      assert.equal((await fetch(url+'/calibration-test-plan')).status,200);await demand(0,0,false);assert.equal(driveRequests,0);page.off('request',watch);
      await page.locator('#calibrationDraft summary').click();
    });
    let exported;
    await test('planner defaults to 36 targets and imports the legacy 18-target design', async () => {
      await page.locator('a[href="/planner"]').click();
      await page.waitForURL(url+'/planner');
      assert.equal(await page.locator('#stationRows tr').count(),12);
      await page.locator('#settingsBtn').click();await page.locator('#gridBtn').click();
      const grid=await page.evaluate(()=>window.PlannerUI.getPlan());
      assert.equal(grid.stations.length,12);assert.equal(new Set(grid.stations.map(s=>s.y_mm)).size,2);
      assert.ok(grid.stations[6].x_mm>grid.stations[7].x_mm);
      await page.locator('#resetBtn').click();

      await page.locator('#closeSettings').click();await page.locator('#simSpeed').selectOption('1');
      await page.locator('#previewBtn').click();
      await until(async()=> (await page.locator('#simStatus').innerText()).includes('S1'), 'preview first station');
      await page.locator('#stopBtn').click();
      await page.locator('#settingsBtn').click();const downloadPromise=page.waitForEvent('download');
      await page.locator('#jsonBtn').click();const download=await downloadPromise;
      const file=path.join(output,'exported-design.json');await download.saveAs(file);
      exported=JSON.parse(fs.readFileSync(file,'utf8'));
      assert.equal(exported.derived.samples.length,36);assert.equal(exported.derived.stationary_time_s,135);
      await page.locator('#importFile').setInputFiles(path.join(root,'example_plan.json'));
      await until(async()=> (await page.locator('#toast').innerText()).includes('Complete plan imported and validated'),'design import completed');
    });
    await test('edited coordinates and wait times transfer from planner to controller', async () => {
      await page.locator('#tableBtn').click();
      await page.locator('#stationRows input[data-id="S1"][data-field="x_mm"]').fill('260');
      await page.locator('#stationRows input[data-id="S1"][data-field="x_mm"]').press('Tab');
      await until(async()=> (await page.evaluate(()=>window.PlannerUI.getPlan())).stations[0].x_mm===260,'edited coordinate committed');
      await page.locator('#closeTable').click();
      // Short intervals keep this test quick. The original 2+5 second boundaries are tested in Python.
      await page.locator('#closeSettings').click();await page.locator('#timingBtn').click();await page.locator('#defaultDwell').fill('0.1');await page.locator('#applyDwell').click();
      await page.locator('#settle').fill('0.1');await page.locator('#closeTiming').click();await page.locator('#settingsBtn').click();
      await page.locator('#handoffBtn').click();await page.waitForURL(url+'/debug#validationPanel');
      await until(async()=> (await page.locator('#planSummary').innerText()).includes('18 targets'), 'plan handoff');
      const report=await (await fetch(url+'/api/validation')).json();
      assert.equal(report.schedule[0].x_mm,260);assert.equal(report.schedule[0].settle_s,.1);assert.equal(report.schedule[0].dwell_s,.1);
    });
    await test('all 18 target timers require confirmation and persist an honest report', async () => {
      await page.locator('#arrivalNotes').fill('Timing-only automated rehearsal; no hardware arrival or sensor measurement.');
      for(let index=0;index<18;index++){
        await until(()=>page.locator('#startSample').isEnabled(),'sample ready');
        await page.locator('#startSample').click();
        await until(async()=> (await (await fetch(url+'/api/validation')).json()).next_index===index+1,'sample '+index+' completed');
      }
      const report=await (await fetch(url+'/api/validation')).json();
      assert.equal(report.samples.length,18);assert.equal(report.live,false);
      assert.ok(report.samples.every(s=>s.result==='timer_completed'&&!s.sensor_measurement_taken&&s.arrival.confirmation==='timing_only'));
      assert.ok(report.samples.every(s=>s.elapsed_s>=.2));
      const saved=JSON.parse(fs.readFileSync(path.join(report.saved_to,'validation.json'),'utf8'));
      assert.equal(saved.next_index,18);
      const events=fs.readFileSync(path.join(report.saved_to,'controller_log.jsonl'),'utf8').trim().split(/\r?\n/).map(JSON.parse);
      assert.equal(events.filter(e=>e.event==='sample_timer_completed').length,18);
      assert.ok(events.every(e=>e.live===false));
      await page.locator('#downloadRecord').scrollIntoViewIfNeeded();
      const downloadPromise=page.waitForEvent('download');await page.locator('#downloadRecord').click();
      await (await downloadPromise).saveAs(path.join(output,'e2e-session-report.json'));
      await demand(0,0,false);
    });
    await test('manual station measurements, dimensioned marking export and repeatability persist separately',async()=>{
      const marking=page.waitForEvent('download');await page.locator('#markingCSV').click();
      await (await marking).saveAs(path.join(output,'station-marking-mm.csv'));
      assert.ok(fs.readFileSync(path.join(output,'station-marking-mm.csv'),'utf8').includes('front-left-deck'));
      await page.locator('#saveTrial').click();
      assert.ok((await page.locator('#validationMessage').innerText()).includes('blank is not zero'));
      await page.locator('#actualHeading').fill('0');await page.locator('#trialUncertainty').fill('1');
      await page.locator('#trialNotes').fill('Software example only, known 3/4/5 mm triangle. No physical measurement.');
      for(const [trial,x,y] of [[1,263,319],[2,257,311]]){
        await page.locator('#trialNumber').fill(String(trial));await page.locator('#actualX').fill(String(x));await page.locator('#actualY').fill(String(y));
        await page.locator('#saveTrial').click();
        await until(async()=>(await(await fetch(url+'/api/validation')).json()).station_trials.length===trial,'station trial persisted');
      }
      const r=await(await fetch(url+'/api/validation')).json();
      assert.equal(r.station_summary[0].radial_rms_error_mm,5);
      assert.equal(r.station_summary[0].bias_x_mm,0);
      assert.equal(r.station_summary[0].evidence,'software_example');
      assert.equal(r.station_trials[0].observed_dwell_s,null);
      assert.equal(r.next_index,18);
      const trialDownload=page.waitForEvent('download');await page.locator('#trialsCSV').click();
      await(await trialDownload).saveAs(path.join(output,'station-trials.csv'));
      assert.ok(fs.readFileSync(path.join(output,'station-trials.csv'),'utf8').includes('radial_error_mm'));
      const reportDownload=page.waitForEvent('download');await page.locator('#downloadRecord').click();
      await(await reportDownload).saveAs(path.join(output,'e2e-session-report.json'));
      assert.ok((await page.locator('#telemetryFields').innerText()).includes('missing'));
    });
    await ready();
    assert.deepEqual(errors, [], 'Browser console/page errors');
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.screenshot({ path: path.join(output, 'simulator-desktop.png'), fullPage: false, timeout:10000 });
    await page.setViewportSize({ width: 390, height: 844 });
    await test('mobile layout fits viewport', async () => {
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    });
    await page.screenshot({ path: path.join(output, 'simulator-mobile.png'), fullPage: false, timeout:10000 });
    await demand(0, 0, false);
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({
      time: new Date().toISOString(), browser: 'Playwright Chromium', mode: 'simulation',
      passed: results, browserErrors: errors, finalState: await state(),
    }, null, 2));
    console.log(`${results.length} real-browser checks passed; simulation only.`);
  } catch (error) {
    fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({time:new Date().toISOString(),passed:results,error:String(error),browserErrors:errors},null,2));
    if (page) await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: false, timeout:5000 }).catch(() => {});
    throw error;
  } finally {
    if (browser) await browser.close();
    // This child is always our private --simulate process, never a live controller.
    if (server.exitCode === null) {
      const exited = new Promise(resolve => server.once('exit', resolve));
      server.kill(); await exited;
    }
    terminal.end();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
