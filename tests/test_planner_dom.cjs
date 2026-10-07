// Node-only smoke check with a mock DOM. This does not verify browser rendering or pointer behavior.
const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const base=path.resolve(__dirname,'..');
const html=fs.readFileSync(base+'/ContainmentIQ_Cabinet_Planner.html','utf8');
const script=html.split('<script>')[1].split('</script>')[0];
const nodes={};
for(const match of html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"[^>]*>/g)){const tag=match[0];nodes[match[2]]={id:match[2],value:tag.match(/\bvalue="([^"]*)"/)?.[1]??'',checked:/\bchecked\b/.test(tag),disabled:false,dataset:{},style:{},attrs:{},listeners:{},classList:{toggle(){}},setAttribute(k,v){this.attrs[k]=String(v);},addEventListener(k,v){this.listeners[k]=v;},querySelectorAll(){return[];},querySelector(){return null;},click(){},focus(){},remove(){},setPointerCapture(){}};}
for(const n of Object.values(nodes)){let v=String(n.value);Object.defineProperty(n,'value',{get(){return v;},set(x){v=String(x);}});}
nodes.spacing.value='centers';nodes.simSpeed.value='10';
const context={window:{},document:{getElementById:id=>{if(!nodes[id])throw Error('Missing #'+id);return nodes[id];},createElement:()=>({click(){},remove(){}}),body:{append(){}}},setTimeout:()=>1,clearTimeout(){},requestAnimationFrame:()=>1,cancelAnimationFrame(){},performance:{now:()=>100},console,Blob,URL};vm.createContext(context);vm.runInContext(script,context);
const core=context.window.PlannerCore,ui=context.window.PlannerUI;
assert.equal(core.validate(ui.getPlan()).valid,true);
assert.equal(nodes.stationCount.textContent,12);assert.equal(nodes.sampleCount.textContent,36);
assert(nodes.planSvg.innerHTML.includes('class="station stationfocus"'));
// A numerical table edit may be outside the allowed envelope; it must be flagged, not silently clamped.
nodes.stationRows.listeners.change({target:{dataset:{id:'S1',field:'x_mm'},value:'-5'}});
assert.equal(ui.getPlan().stations[0].x_mm,-5);assert.equal(core.validate(ui.getPlan()).valid,false);assert.equal(nodes.jsonBtn.disabled,true);
nodes.resetBtn.listeners.click();assert.equal(core.validate(ui.getPlan()).valid,true);
// Blank dimension must remain invalid, rather than falling back to zero / default.
nodes.width.value='';nodes.width.listeners.input();assert.equal(core.validate(ui.getPlan()).valid,false);assert.equal(nodes.previewBtn.disabled,true);
nodes.resetBtn.listeners.click();assert.equal(core.validate(ui.getPlan()).valid,true);
// Geometry edits revoke a user measurement assertion.
nodes.measurementNote.value='Measured mock record';nodes.measurementNote.listeners.input();nodes.measured.checked=true;nodes.measured.listeners.change();assert.equal(ui.getPlan().profile.measured,true);nodes.width.value='1799';nodes.width.listeners.input();assert.equal(ui.getPlan().profile.measured,false);
console.log('DOM smoke: startup, SVG output, raw out-of-bounds edit, empty dimension, disabled export and measurement-reset passed. Mock DOM is not a browser UI test.');
