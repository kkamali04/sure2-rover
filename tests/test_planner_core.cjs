/* Independent tests of the actual inline planner core. Run: node tests/test_planner_core.cjs */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const kit = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(kit, 'ContainmentIQ_Cabinet_Planner.html'), 'utf8');
const end = 'window.PlannerCore=PlannerCore;';
const source = html.slice(html.indexOf('const PlannerCore='), html.indexOf(end) + end.length);
const context = {window: {}};
vm.createContext(context);
vm.runInContext(source, context);
const C = context.window.PlannerCore;
const normalize = x => JSON.parse(JSON.stringify(x));
let checks = 0;
function test(name, fn) { fn(); checks++; process.stdout.write(`PASS ${name}\n`); }
function fresh() { const p = C.defaultPlan(); p.stations = C.distribute(p, 6, 315); return p; }

test('alternating rows keep six stations separate from three heights',()=>{
 const p=fresh();p.stations=C.distributeRows(p,2,3,4);
 assert.equal(p.stations.length,6);assert.equal(C.samples(p).length,18);
 assert.equal(new Set(p.stations.map(s=>s.y_mm)).size,2);
 assert.ok(p.stations[0].x_mm<p.stations[1].x_mm);assert.ok(p.stations[3].x_mm>p.stations[4].x_mm);
 assert.equal(C.validate(p).valid,true);assert.ok(C.validate(p).warnings.some(w=>w.includes('turning')));
 assert.throws(()=>C.distributeRows(p,0,3));assert.throws(()=>C.distributeRows(p,20,20));
});

test('actual example imports and produces eighteen samples', () => {
  const example = JSON.parse(fs.readFileSync(path.join(kit, 'example_plan.json'), 'utf8'));
  const p = C.importObject(example);
  assert.equal(C.validate(p).valid, true);
  assert.equal(C.samples(p).length, 18);
  assert.equal(C.stationaryTime(p), 126);
  assert.deepEqual(normalize(C.samples(p)), example.derived.samples);
});

test('CSV station roundtrip retains exact numeric data', () => {
  const p = fresh();
  p.stations[0].dwell_s = 7.25;
  const back = C.parseStationCSV(C.stationCSV(p), p);
  assert.deepEqual(normalize(back.stations), normalize(p.stations));
  assert.equal(C.sampleCSV(p).trim().split(/\r?\n/).length, 19);
});

test('malformed CSV and numeric coercion are rejected', () => {
  for (const bad of ['NaN', 'Infinity', '0xFF', 'true', '']) {
    assert.throws(() => C.parseStationCSV(`id,x_mm,y_mm,dwell_s\nS1,${bad},315,5\n`, fresh()));
  }
  assert.throws(() => C.parseStationCSV(C.sampleCSV(fresh()), fresh()));
});

test('nonfinite values and numeric strings cannot import or export', () => {
  for (const bad of [NaN, Infinity, -Infinity, true, '200']) {
    const p = fresh(); p.stations[0].x_mm = bad;
    assert.equal(C.validate(p).valid, false);
    assert.throws(() => C.importObject(p));
    assert.throws(() => C.exportObject(p));
  }
});

test('unsafe supplied tower and off-wall probe are rejected', () => {
  const high = fresh(); high.profile.mount.max_height_mm = 1064.4;
  assert.equal(C.validate(high).valid, false);
  const wide = fresh(); wide.profile.mount.width_mm = 760;
  assert.equal(C.validate(wide).valid, false);
  const offset = fresh(); offset.profile.probe.offset_y_mm = 10000;
  assert.equal(C.validate(offset).valid, false);
});

test('derived values are recalculated after import', () => {
  const raw = C.exportObject(fresh());
  raw.derived.sample_count = 999;
  raw.derived.hardware_ready = true;
  raw.derived.samples = [];
  const p = C.importObject(raw);
  assert.equal(p.derived, undefined);
  const out = C.exportObject(p);
  assert.equal(out.derived.sample_count, 18);
  assert.equal(out.derived.hardware_ready, false);
  assert.equal(out.derived.samples.length, 18);
});

test('fixed-heading limit and custom Y warning are explicit', () => {
  const p = fresh(); p.motion.heading_deg = 90;
  assert.equal(C.validate(p).valid, false);
  p.motion.heading_deg = 0; p.stations[0].y_mm += 1;
  assert.ok(C.validate(p).warnings.some(w => /cannot translate sideways/.test(w)));
});

test('millimeter geometry and offsets agree with Python on real JS export', () => {
  const p = fresh();
  p.profile.probe.offset_x_mm = 125;
  p.profile.probe.offset_y_mm = -75;
  p.stations = C.distribute(p, 6, 315);
  const out = C.exportObject(p);
  const py = spawnSync(process.env.PYTHON || 'python', ['-c',
    'import json,sys; from rover_test import validate_plan; print(json.dumps(validate_plan(json.load(sys.stdin))))'],
    {cwd:kit, input:JSON.stringify(out), encoding:'utf8'});
  assert.equal(py.status, 0, py.stderr);
  const result = JSON.parse(py.stdout);
  const b = C.limits(p), pb = result.center_bounds_mm;
  for (const [j,k] of [['xMin','xmin'],['xMax','xmax'],['yMin','ymin'],['yMax','ymax']]) assert.equal(b[j], pb[k]);
  assert.equal(result.schedule.length, 18);
  const js = C.samples(p);
  for (let i=0; i<18; i++) {
    assert.equal(js[i].probe_x_mm, result.schedule[i].sensor_x_mm);
    assert.equal(js[i].probe_y_mm, result.schedule[i].sensor_y_mm);
    assert.equal(js[i].z_mm, result.schedule[i].sensor_z_mm);
  }
  assert.equal(C.stationaryTime(p), result.acquisition_seconds);
});

test('endpoint spacing stays inside fractional exact bounds', () => {
  const p = fresh(); p.profile.keepout.side_mm = 25.00005;
  p.stations = C.distribute(p, 6, 315, 'endpoints');
  const result = C.validate(p);
  assert.equal(result.valid, true, JSON.stringify(result.errors));
});

test('SVG uses equal unit scale and no remote scripts', () => {
  assert.ok(html.includes('preserveAspectRatio="xMidYMid meet"'));
  assert.ok(html.includes('W=c.width_mm*s,H=vertical*s'));
  assert.equal(/<script[^>]+src\s*=\s*["\']https?:/i.test(html), false);
  assert.equal(/navigator\.serial|new WebSocket|fetch\s*\(/.test(source), false);
});
test('route turns and rotated probe targets agree with Python',()=>{
 const p=fresh();p.motion.heading_axis='route';p.profile.probe.offset_x_mm=40;p.profile.probe.offset_y_mm=15;p.stations=C.distributeRows(p,2,6,10);
 p.stations[5].departure='left90';p.stations[6].departure='left90';const out=C.exportObject(p);
 const py=spawnSync(process.env.PYTHON||'python',['-c','import json,sys; from rover_test import validate_plan; print(json.dumps(validate_plan(json.load(sys.stdin))))'],{cwd:kit,input:JSON.stringify(out),encoding:'utf8'});assert.equal(py.status,0,py.stderr);const result=JSON.parse(py.stdout),r=C.route(p),samples=C.samples(p);
 assert.equal(r[5].turn_deg,90);assert.equal(r[6].turn_deg,90);for(let i=0;i<12;i++){assert.equal(r[i].heading_deg,result.route_preview[i].heading_deg);assert.equal(r[i].turn_deg,result.route_preview[i].turn_deg);}for(let i=0;i<36;i++){assert.equal(samples[i].probe_x_mm,result.schedule[i].sensor_x_mm);assert.equal(samples[i].probe_y_mm,result.schedule[i].sensor_y_mm);}
 p.stations[5].departure='right90';assert.equal(C.validate(p).valid,false);
});
test('original preview asset proxy dimensions and Three license are preserved',()=>{
 const T=require('../preview/vendor/three.min.js');const ctx={THREE:T};vm.createContext(ctx);vm.runInContext(fs.readFileSync(path.join(kit,'preview/assets.js'),'utf8'),ctx);
 const rover=ctx.CIQAssets.createRover();rover.remove(rover.userData.lift);const size=new T.Box3().setFromObject(rover).getSize(new T.Vector3());for(const [actual,expected] of [[size.x,194],[size.z,168],[size.y,100]])assert(Math.abs(actual-expected)<.001);
 const chamber=ctx.CIQAssets.createChamber();const floor=new T.Box3().setFromObject(chamber.children[0]).getSize(new T.Vector3());assert.equal(floor.x,1800);assert.equal(floor.z,630);assert(fs.readFileSync(path.join(kit,'preview/vendor/THREE-LICENSE.txt'),'utf8').includes('MIT License'));
});
process.stdout.write(`${checks} planner-core checks passed. No hardware used.\n`);
