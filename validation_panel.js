'use strict';
(() => {
 const panel=document.getElementById('validationPanel');
 panel.innerHTML=`<h2>Offline test record and design timing</h2>
 <p id="recordLocation">Connecting to the session record…</p>
 <p>Commands, input events, errors and your observations are saved on this computer. An accepted command is not proof of wheel movement.</p>
 <h3>1. Record each physical check</h3>
 <p>With wheels raised, test each control yourself, press STOP, then record what you observed. Try A and D alone before W+A / W+D. Opposing keys (W+S or A+D) stop and disarm.</p>
 <details><summary><strong>A/D does not turn? Run this short check</strong></summary><ol><li>Support all wheels clear of the surface. Keep PWM at 0.10. ARM, briefly hold the on-screen PIVOT LEFT button, then release and STOP.</li><li>While held, expect Left demand -0.10 and Right demand +0.10. For PIVOT RIGHT, expect +0.10 and -0.10. Watch the wheels on each side, not the raised chassis.</li><li>Repeat using A/D after clicking the page heading to move focus out of inputs. If mouse works but keys do not, record that difference.</li><li>If values stay zero, record the arm state and any message. If values have opposite signs but wheels stay still, record that; a transmitted command is not proof the installed firmware applied it.</li><li>If opposite-side wheels spin with wheels raised but it will not pivot on the floor, floor/load resistance is a possibility. Do not increase PWM or change firmware during this diagnostic.</li></ol><p>Save separate Left pivot and Right pivot observations. Include whether wheels were raised, displayed L/R values, which wheels spun, and any error.</p></details>
 <label>Check <select id="checkName"><option>Forward / reverse</option><option>Left pivot (A alone)</option><option>Right pivot (D alone)</option><option>W+A / W+D steering</option><option>S+A / S+D steering</option><option>Release all keys stops wheels</option><option>Release steering key resumes straight</option><option>STOP / Space / Escape</option><option>Window focus loss stops wheels</option><option>Connection / other issue</option></select></label>
 <label>Result <select id="checkResult"><option value="not_tested">Not tested</option><option value="pass">Observed pass</option><option value="fail">Observed failure</option></select></label>
 <p><textarea id="checkNotes" rows="3" maxlength="2000" style="width:100%" placeholder="What did the wheels actually do? Include PWM and any error."></textarea></p>
 <button id="saveObservation">Save observation</button> <button id="downloadRecord">Download session report</button> <button id="downloadSession">Download complete session ZIP</button>
 <p id="observationCount"></p>
 <h3>2. Load your design</h3>
 <p><a href="/planner">Open cabinet planner</a> — edit or import your design, then export <strong>Complete plan JSON</strong>. Import that file below. Changing tabs stops and disarms the controller.</p>
 <input id="testPlanFile" type="file" accept=".json,application/json" aria-label="Import design for timing test">
 <p id="planSummary">No plan loaded. Your current browser design is not replaced.</p>
 <div id="targetDiagram" aria-label="Planned station map"></div>
 <h3>3. Manual horizontal station trials</h3>
 <p>Mark rover-center targets from the front-left deck datum: +X right, +Y rear, millimeters. The rover faces +X at each target. Drive yourself, STOP, measure its center and heading, then save a trial. This is separate from the three probe heights and their timers.</p>
 <button id="markingCSV">Export marking coordinates</button> <button id="trialsCSV">Export measured trials CSV</button>
 <p id="stationDatum"></p>
 <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px">
 <label>Station <select id="trialStation"></select></label>
 <label>Trial number <input id="trialNumber" type="number" min="1" value="1" style="width:100%"></label>
 <label>Evidence <select id="trialEvidence"><option value="software_example">Software example only</option><option value="physical_manual">Physical manual measurement</option></select></label>
 <label>Final approach <select id="trialApproach"><option>+X</option><option>-X</option><option>+Y</option><option>-Y</option><option>other</option></select></label>
 <label>Measured rover X (mm) <input id="actualX" type="number" step="any" style="width:100%"></label>
 <label>Measured rover Y (mm) <input id="actualY" type="number" step="any" style="width:100%"></label>
 <label>Measured heading (degrees) <input id="actualHeading" type="number" min="-180" max="180" step="any" style="width:100%"></label>
 <label>Measurement uncertainty (mm) <input id="trialUncertainty" type="number" min="0" step="any" style="width:100%"></label>
 <label>Observed dwell (s, optional) <input id="observedDwell" type="number" min="0" step="any" style="width:100%"></label>
 </div>
 <p>Heading 0° faces +X; positive rotation points toward +Y. Blank dwell means unmeasured. Dwell is elapsed time, not sensor acquisition. Probe X/Y inferred from your center/heading and configured offsets is an estimate.</p>
 <textarea id="trialNotes" rows="2" maxlength="2000" style="width:100%" placeholder="Required: measuring instrument, datum, load and assembly, or identify software-only example."></textarea>
 <button id="saveTrial">Save measured station trial</button>
 <div id="trialSummary" style="overflow-x:auto"></div>
 <h3>4. Three-height timing rehearsal</h3>
 <p>This displays planned targets; it does not drive to coordinates or move the lift. Position and height are not measured by this software. First use a timing-only rehearsal. For a physical run, independently verify clearance, position and height before confirming each arrival.</p>
 <p id="nextTarget"></p>
 <label>Arrival evidence <select id="arrivalMode"><option value="timing_only">Timing-only rehearsal — no arrival verified</option><option value="operator_verified">I independently verified position and height</option></select></label>
 <p><textarea id="arrivalNotes" rows="2" maxlength="2000" style="width:100%" placeholder="Required: timing-only rehearsal, or how you checked position/height."></textarea></p>
 <button id="startSample">Start this sample's wait times</button> <button id="cancelSample">Cancel timer</button>
 <p id="sampleTimer" role="status"></p>
 <p>Press STOP before starting a timer. Arming is blocked during settle/dwell. Each next target requires your confirmation. STOP, a hidden tab, connection failure or shutdown cancels an active timer. A finished timer does not mean sensor data was collected.</p>
 <h3>Received rover fields</h3><button id="readTelemetry">Read battery + IMU (stopped)</button><p id="telemetryReadStatus" role="status"></p><p>Missing data stay missing. Recent responses do not prove fresh sensor readings. These units describe the reference firmware; the installed version is still unverified. PWM is a command, never measured speed. For a stationary discovery capture, use the separate Read telemetry launcher after closing live control.</p>
 <div id="telemetryFields" style="overflow-x:auto">No rover telemetry observed.</div>
 <details id="calibrationDraft"><summary><strong>5. Motion calibration and preliminary route draft</strong></summary>
 <p>Operate the manual controls yourself, STOP, then record what you measured. A command log cannot measure travel distance. Use at least three trials for each direction at the same PWM, surface and load. <a href="/calibration-test-plan">Read the test plan</a>.</p>
 <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px">
 <label>Direction <select id="calDirection"><option value="forward">Forward</option><option value="reverse">Reverse</option><option value="left">Left pivot</option><option value="right">Right pivot</option></select></label>
 <label>Commanded PWM <input id="calPWM" type="number" min="0.05" max="0.25" step="0.01" placeholder="e.g. 0.10"></label>
 <label>Drive interval · s <input id="calDuration" type="number" min="0.05" max="120" step="any"></label>
 <label><span id="calDisplacementLabel">Start-to-rest distance · mm</span><input id="calDisplacement" type="number" min="0" step="any"></label>
 <label>Release-to-rest travel · mm (optional) <input id="calStopDistance" type="number" min="0" step="any"></label>
 <label>Surface / test area <input id="calSurface" maxlength="200" placeholder="Describe the actual floor"></label>
 <label>Rover/load/battery condition <input id="calConfiguration" maxlength="200" placeholder="Keep trials in the same condition"></label>
 <label>Evidence <select id="calEvidence"><option value="software_example">Software example only</option><option value="physical_manual">Physical manual measurement</option></select></label>
 <label>Drive interval source <select id="calDurationSource"><option value="stopwatch_video">Stopwatch / video</option><option value="command_timestamps">Command timestamps (not motor timing)</option></select></label>
 </div><p><textarea id="calNotes" rows="2" maxlength="2000" style="width:100%" placeholder="Required: measuring method, battery voltage if observed, wheel behavior, drift, or software-example label."></textarea></p>
 <button id="saveCalibration">Save calibration trial</button><button id="compileDraft">Prepare timed-route draft</button><button id="downloadDraft">Download draft JSON</button>
 <p id="calibrationSummary"></p><p id="timedDraftSummary"></p>
 <p>Preparing/downloading a draft sends no movement commands. Physical route execution is not implemented. Estimated times are open-loop; X/Y remain targets. No lift control or sensor acquisition is performed.</p>
 </details><p id="validationMessage" role="status"></p>`;
 const $=id=>document.getElementById(id);
 let data=null,busy=false,renderedPlan=null,polling=false,stationPlan=null,telemetry=null;
 const message=text=>{$('validationMessage').textContent=text;};
 async function post(body){
   if(busy)return;
   busy=true;
   try{data=await window.RemoteControllerUI.validation(body);render();message('Saved to this session on your computer.');}
   catch(error){message('Not saved: '+error.message);}
   finally{busy=false;}
 }
 function drawPlan(){
   const holder=$('targetDiagram');holder.replaceChildren();if(!data.plan)return;
   const svgNS='http://www.w3.org/2000/svg';const svg=document.createElementNS(svgNS,'svg');
   const w=data.plan.profile.chamber.width_mm,h=data.plan.profile.chamber.depth_mm;
   svg.setAttribute('viewBox',`-45 -45 ${w+90} ${h+90}`);svg.style.cssText='width:100%;max-height:280px;background:#f4f0e8;border:1px solid #ddd';
   const rect=document.createElementNS(svgNS,'rect');for(const [k,v] of Object.entries({x:0,y:0,width:w,height:h,fill:'none',stroke:'#333','stroke-width':3}))rect.setAttribute(k,v);svg.append(rect);
   const active=data.schedule[data.next_index];
   for(const station of data.plan.stations){
     const dot=document.createElementNS(svgNS,'circle');dot.setAttribute('cx',station.x_mm);dot.setAttribute('cy',h-station.y_mm);dot.setAttribute('r',Math.max(8,w/100));dot.setAttribute('fill',station.id===active?.station?'#a7643a':'#34654d');svg.append(dot);
     const label=document.createElementNS(svgNS,'text');label.setAttribute('x',station.x_mm);label.setAttribute('y',h-station.y_mm-25);label.setAttribute('text-anchor','middle');label.setAttribute('font-size',Math.max(20,w/55));label.textContent=station.id;svg.append(label);
   }
   holder.append(svg);
   const caption=document.createElement('p');caption.textContent='Planned rover-center targets, viewed from above; highlighted point is the next target. This is not a live-position map.';holder.append(caption);
 }
 function render(){
   if(!data)return;
   const controller=window.RemoteControllerUI.getState();
   $('recordLocation').textContent=`Session ${data.run_id} · ${data.live?'LIVE':'SIMULATION'} · ${data.saved_to||'No disk recording configured'}`;
   $('observationCount').textContent=`${data.observations.length} saved observations. Physical outcomes are your reports.`;
   $('saveObservation').disabled=controller.armed;
   $('testPlanFile').disabled=controller.armed||!!data.timer;
   $('readTelemetry').disabled=controller.armed||controller.neutralPending||controller.telemetryBusy||!controller.connected||!!data.timer;
   $('telemetryReadStatus').textContent=controller.telemetryBusy?'Reading base and IMU through the sole hardware connection...':telemetry?.fault?'Feedback issue: '+telemetry.fault:'Read only when stopped. Fields below age until you request another reading.';
   $('saveTrial').disabled=!data.plan||controller.armed||controller.neutralPending||!!data.timer;
   $('markingCSV').disabled=!data.plan;
   const planKey=JSON.stringify(data.plan);
   if(stationPlan!==planKey){stationPlan=planKey;$('trialStation').replaceChildren();for(const s of data.plan?.stations||[]){const o=document.createElement('option');o.value=s.id;o.textContent=`${s.id}: X ${s.x_mm}, Y ${s.y_mm} mm`;$('trialStation').append(o);}}
   $('stationDatum').textContent=data.plan?`Profile ${data.plan.profile.measured?'marked measured by operator':'PROVISIONAL: not measured'}. Probe offsets at heading 0°: X ${data.plan.profile.probe.offset_x_mm}, Y ${data.plan.profile.probe.offset_y_mm} mm. Mark the physical center reference on the rover. No obstacle or swept-turn clearance is certified.`:'';
   table('trialSummary',['Station / approach / evidence','n','Mean X/Y error mm','Sample SD X/Y mm','Radial RMS / max mm'],(data.station_summary||[]).map(s=>[`${s.station} / ${s.approach} / ${s.evidence}`,s.n,`${fmt(s.bias_x_mm)} / ${fmt(s.bias_y_mm)}`,`${fmt(s.sample_sd_x_mm)} / ${fmt(s.sample_sd_y_mm)}`,`${fmt(s.radial_rms_error_mm)} / ${fmt(s.maximum_error_mm)}`]));
   if(telemetry)table('telemetryFields',['Field / units','Type','Value','Support / receipt age','Observed receipt Hz','Freshness / limitations'],telemetry.fields.map(f=>[`${f.field} / ${f.units}`,f.kind,f.value??'missing',`${f.support}; ${f.receive_status}, ${fmt(f.receive_age_s)} s`,fmt(f.observed_receive_hz),f.freshness+'; '+f.limitations]));
   $('planSummary').textContent=data.plan?`${data.plan.stations.length} stations × ${data.plan.heights_mm.length} heights = ${data.schedule.length} targets. Settle + dwell: ${data.schedule.reduce((sum,s)=>sum+s.settle_s+s.dwell_s,0).toFixed(2)} s; excludes all travel and lift time. ${data.plan_warnings.join(' ')}`:'No plan loaded.';
   const target=data.schedule[data.next_index];
   $('nextTarget').textContent=target?`Target ${data.next_index+1}/${data.schedule.length}: ${target.station} — rover center X ${target.x_mm}, Y ${target.y_mm} mm; probe center X ${target.sensor_x_mm}, Y ${target.sensor_y_mm}, Z ${target.sensor_z_mm} mm. Settle ${target.settle_s} s, dwell ${target.dwell_s} s.`:data.schedule.length?'All target timers finished. Review your observations; physical completion is not automatically verified.':'Import your plan to see the target sequence.';
   $('startSample').disabled=!target||!!data.timer||controller.armed||controller.neutralPending||!controller.connected;
   $('cancelSample').disabled=!data.timer;
   $('sampleTimer').textContent=data.timer?`${data.timer.phase.toUpperCase()}: ${data.timer.remaining_s.toFixed(1)} seconds remaining`:`${data.samples.filter(s=>s.result==='timer_completed').length} timers completed; ${data.samples.filter(s=>s.result==='cancelled').length} cancelled. Waiting for your next action.`;
   const mapKey=JSON.stringify([data.plan,data.next_index]);if(mapKey!==renderedPlan){renderedPlan=mapKey;drawPlan();}
   const blocked=controller.armed||controller.neutralPending||!!data.timer||!controller.connected;
   $('downloadSession').disabled=blocked;
   $('saveCalibration').disabled=blocked;$('compileDraft').disabled=blocked||!data.plan;
   $('downloadDraft').disabled=!data.timed_route_draft;
   $('calEvidence').querySelector('[value="physical_manual"]').disabled=!data.live;
   $('calibrationSummary').textContent=(data.calibration_summary||[]).map(g=>`${g.direction}: ${g.count} trials, ${g.mean_effective_rate.toFixed(2)} ${g.units} effective displacement/interval, spread ${g.sample_sd===null?'not available':g.sample_sd.toFixed(2)}; PWM ${g.pwm}; ${g.surface}; ${g.configuration}; ${g.evidence}`).join(' | ')||'No calibration measurements saved. Values are not inferred from motor commands.';
   const draft=data.timed_route_draft;
   $('timedDraftSummary').textContent=draft?`${draft.status}: ${draft.steps.filter(s=>s.kind==='estimated_motion').length} estimated motion legs, ${draft.estimated_rover_motion_seconds.toFixed(2)} s rover motion plus ${draft.stationary_seconds.toFixed(2)} s settle/dwell; excludes manual positioning/lift work. ${draft.steps.filter(s=>s.extrapolated).length} legs extrapolate beyond trial distances/angles. Hardware execution disabled.`:'No timed-route draft prepared. Motion measurements are required first.';
 }
 function fmt(value){return value===null||value===undefined?'unknown':Number(value).toFixed(2);}
 function table(id,headers,rows){const holder=$(id);holder.replaceChildren();const t=document.createElement('table');t.style.cssText='border-collapse:collapse;font-size:12px;width:100%';for(const [i,row] of [headers,...rows].entries()){const tr=document.createElement('tr');for(const value of row){const cell=document.createElement(i===0?'th':'td');cell.style.cssText='text-align:left;border-bottom:1px solid #ddd;padding:6px';cell.textContent=String(value);tr.append(cell);}t.append(tr);}holder.append(t);}
 function csvDownload(name,rows){const cell=v=>{let s=v===null||v===undefined?'':String(v);if(typeof v==='string'&&/^[=+@\-\t\r]/.test(s))s="'"+s;return '"'+s.replaceAll('"','""')+'"';};const text=rows.map(row=>row.map(cell).join(',')).join('\r\n');const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 $('markingCSV').onclick=()=>{if(!data.plan)return;const p=data.plan;csvDownload('station-marking-mm.csv',[['station','rover_center_x_mm','rover_center_y_mm','heading_deg','probe_target_x_mm','probe_target_y_mm','planned_dwell_per_height_s','profile_measured','origin','axes','probe_heights_mm'],...p.stations.map(s=>[s.id,s.x_mm,s.y_mm,0,s.x_mm+p.profile.probe.offset_x_mm,s.y_mm+p.profile.probe.offset_y_mm,s.dwell_s,p.profile.measured,'front-left-deck','X right; Y rear; Z up',p.heights_mm.join(';')])]);};
 $('trialsCSV').onclick=()=>{const rows=data?.station_trials||[];if(!rows.length)return message('No station trials recorded.');const keys=Object.keys(rows[0]);csvDownload('station-trials.csv',[keys,...rows.map(row=>keys.map(k=>row[k]))]);};
 $('saveTrial').onclick=()=>{const numeric=id=>{if(!$(id).value.trim())throw Error('Enter '+id+'; blank is not zero.');const v=Number($(id).value);if(!Number.isFinite(v))throw Error('Enter a finite number for '+id);return v;};try{void post({action:'station_trial',station:$('trialStation').value,trial:numeric('trialNumber'),actual_x_mm:numeric('actualX'),actual_y_mm:numeric('actualY'),heading_deg:numeric('actualHeading'),uncertainty_mm:numeric('trialUncertainty'),approach:$('trialApproach').value,observed_dwell_s:$('observedDwell').value.trim()?numeric('observedDwell'):null,evidence:$('trialEvidence').value,notes:$('trialNotes').value});}catch(error){message(error.message);}};
 $('readTelemetry').onclick=async()=>{try{await window.RemoteControllerUI.readTelemetry();message('Read requested. No movement or rearming requested.');}catch(error){message(error.message);}};
 $('saveObservation').onclick=()=>post({action:'observation',check:$('checkName').value,result:$('checkResult').value,notes:$('checkNotes').value});
 $('testPlanFile').onchange=async event=>{
   const file=event.target.files[0];if(!file)return;
   try{if(file.size>900000)throw Error('Plan must be under 900 KB');await post({action:'import_plan',plan:JSON.parse(await file.text())});}
   catch(error){message('Plan not imported: '+error.message);}finally{event.target.value='';}
 };
 $('startSample').onclick=()=>post({action:'arrived',index:data.next_index,confirmation:$('arrivalMode').value,notes:$('arrivalNotes').value});
 $('cancelSample').onclick=()=>post({action:'cancel_timer'});
 const calNumber=id=>{if(!$(id).value.trim())throw Error('Enter '+id+'; blank is not zero.');const n=Number($(id).value);if(!Number.isFinite(n))throw Error('Enter a finite value for '+id);return n;};
 const calProfile=()=>({pwm:calNumber('calPWM'),surface:$('calSurface').value.trim(),configuration:$('calConfiguration').value.trim(),evidence:$('calEvidence').value,duration_source:$('calDurationSource').value});
 $('calDirection').onchange=()=>{$('calDisplacementLabel').textContent=['left','right'].includes($('calDirection').value)?'Start-to-rest rotation magnitude · deg':'Start-to-rest distance · mm';};
 $('saveCalibration').onclick=()=>{try{void post({action:'calibration_trial',...calProfile(),direction:$('calDirection').value,duration_s:calNumber('calDuration'),displacement:calNumber('calDisplacement'),stop_distance_mm:$('calStopDistance').value.trim()?calNumber('calStopDistance'):null,notes:$('calNotes').value});}catch(e){message(e.message);}};
 $('compileDraft').onclick=()=>{try{void post({action:'compile_timed_draft',profile:calProfile()});}catch(e){message(e.message);}};
 $('downloadDraft').onclick=()=>{if(!data.timed_route_draft)return;const url=URL.createObjectURL(new Blob([JSON.stringify(data.timed_route_draft,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download='sure2-timed-route-draft.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 $('downloadRecord').onclick=async()=>{
   try{const response=await fetch('/api/validation',{cache:'no-store'});if(!response.ok)throw Error('Report unavailable');const report=await response.json();
     const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`rover-test-${report.run_id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
   }catch(error){message(error.message);}
 };
 $('downloadSession').onclick=async()=>{try{const response=await fetch('/api/session-export',{cache:'no-store'});if(!response.ok)throw Error('STOP and cancel timers before downloading logs.');const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download=`sure2-session-${data.run_id}.zip`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('Downloaded this session: raw retained logs and reports. Keep it outside the Git repository.');}catch(error){message(error.message);}};
 async function poll(){if(polling||busy)return;polling=true;try{const responses=await Promise.all(['/api/validation','/api/status'].map(path=>fetch(path,{cache:'no-store',signal:AbortSignal.timeout(3000)})));if(responses.some(r=>!r.ok))throw Error('Session record unavailable.');const [report,status]=await Promise.all(responses.map(r=>r.json()));data=report;telemetry=status.telemetry;render();}catch(error){message(error.message);}finally{polling=false;}}
 void poll();setInterval(poll,500);
})();
