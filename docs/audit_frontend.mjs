// Offline checks of the real TypeScript/Vue source using installed dependencies.
// Run with the WSL Node binary: node docs/audit_frontend.mjs
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
process.chdir(root);
assert.equal(process.env.WSL_DISTRO_NAME,"Ubuntu22.04.3");
assert.equal(execFileSync("git",["rev-parse","--show-toplevel"],{encoding:"utf8"}).trim(),root);
const frontend=path.join(root,"code/chapter14/helloagents-deepresearch/frontend");
const require=createRequire(path.join(frontend,"package.json"));
const ts=require("typescript");
const vue=require("vue");
const checks=[];
const encoder=new TextEncoder();
function compile(code, localRequire=require){
 const output=ts.transpileModule(code,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
 const module={exports:{}};
 new Function("require","module","exports",output)(localRequire,module,module.exports);
 return module.exports;
}
const source=fs.readFileSync(path.join(frontend,"src/services/api.ts"),"utf8");
const api=compile(source.replace("import.meta.env.VITE_API_BASE_URL",'"http://fake.invalid"'));
async function response(chunks, callback=()=>{}, hold=false){
 let cancelled=false, stream;
 globalThis.fetch=async(_url,options)=>{
  stream=new ReadableStream({start(controller){
   for(const item of chunks)controller.enqueue(item instanceof Uint8Array?item:encoder.encode(item));
   if(!hold)controller.close();
  },cancel(){cancelled=true;}});
  return new Response(stream,{headers:{"content-type":"text/event-stream"}});
 };
 const events=[];
 await api.runResearchStream({topic:"fake"},e=>{events.push(e);callback(e);});
 return {events,cancelled,stream};
}
await(async function utf8_and_lf_are_supported(){
 const data=encoder.encode('data: {"type":"status","message":"中文"}\n\ndata: {"type":"done"}\n\n');
 const result=await response([...data].map(byte=>new Uint8Array([byte])));
 assert.deepEqual(result.events.map(x=>x.type),["status","done"]);
 assert.equal(result.events[0].message,"中文"); checks.push("F01 UTF-8 and arbitrary byte boundaries: supported");
})();
await(async function crlf_multiple_frames_fail(){
 const result=await response(['data: {"type":"status"}\r\n\r\ndata: {"type":"done"}\r\n\r\n']);
 assert.equal(result.events.length,0); checks.push("F02 CRLF two-frame stream: zero events (compatibility limitation; current backend uses LF)");
})();
await(async function eof_without_done_is_accepted(){
 const result=await response(['data: {"type":"status"}\n\n']);
 assert.deepEqual(result.events.map(x=>x.type),["status"]);checks.push("F03 EOF before done/error resolves successfully");
})();
await(async function callback_errors_are_swallowed(){
 const result=await response(['data: {"type":"status"}\n\ndata: {"type":"done"}\n\n'],()=>{throw new Error("fake UI failure");});
 assert.equal(result.events.length,2);checks.push("F04 onEvent errors are caught as parse errors");
})();
await(async function reader_not_released_on_done(){
 const result=await response(['data: {"type":"done"}\n\n'],()=>{},true);
 assert.equal(result.cancelled,false);assert.equal(result.stream.locked,true);
 checks.push("F05 done returns with reader lock held and no reader.cancel()");
})();
await(async function abort_signal_reaches_fetch(){
 const controller=new AbortController();let received=false;
 globalThis.fetch=async(_url,options)=>{
  received=options.signal===controller.signal;
  return new Promise((_resolve,reject)=>options.signal.addEventListener("abort",()=>reject(new DOMException("aborted","AbortError")),{once:true}));
 };
 const promise=api.runResearchStream({topic:"fake"},()=>{},{signal:controller.signal});
 controller.abort();await assert.rejects(promise,{name:"AbortError"});assert.equal(received,true);
 checks.push("F06 AbortController is passed to fetch and AbortError propagates");
})();
const appSource=fs.readFileSync(path.join(frontend,"src/App.vue"),"utf8").split('<script lang="ts" setup>')[1].split("</script>")[0];
const requestHandlers=[];
const app=compile(appSource+"\nexport { form,loading,error,isExpanded,todoTasks,reportMarkdown,progressLogs,handleSubmit,startNewResearch,formatTaskStatus };",
 name=>name==="vue"?{...vue,onBeforeUnmount:()=>{}}:name==="./services/api"?{
  runResearchStream:(_payload,onEvent,options)=>new Promise((resolve,reject)=>{
   requestHandlers.push({onEvent,options,resolve,reject});
   options.signal.addEventListener("abort",()=>reject(new DOMException("aborted","AbortError")),{once:true});
  })
 }:require(name));
globalThis.requestAnimationFrame=fn=>fn();
globalThis.window={setTimeout:()=>0};
app.form.topic="fake";
const first=app.handleSubmit();
const request=requestHandlers[0];
request.onEvent({type:"tool_call",task_id:1,event_id:1,tool:"note",agent:"planner",parameters:{},result:"ok"});
request.onEvent({type:"todo_list",tasks:[{id:1,title:"first",status:"pending"},{id:2,title:"second",status:"pending"}]});
request.onEvent({type:"task_status",task_id:1,status:"failed",detail:"fake search timeout"});
request.onEvent({type:"task_status",task_id:2,status:"skipped"});
assert.equal(app.todoTasks.value[0].toolCalls.length,0);
checks.push("F10 planner tool event before todo_list loses structured task log in UI");
assert.equal(app.todoTasks.value[0].status,"failed");
assert.equal(app.formatTaskStatus("failed"),"failed");
assert.equal(app.formatTaskStatus("cancelled"),"cancelled");
assert.equal(app.error.value,"");
assert.equal(app.todoTasks.value[0].notices.length,0);
assert.ok(app.progressLogs.value.some(s=>s.includes("任务跳过")));
checks.push("F07 failed is stored but detail/log/localized label absent; skipped is handled");
app.startNewResearch();
app.form.topic="new";
const second=app.handleSubmit();
assert.equal(app.loading.value,true);
await first;
assert.equal(app.loading.value,false);
checks.push("F08 old aborted request finally resets loading while new request is active");
const current=requestHandlers[1];
current.onEvent({type:"todo_list",tasks:[{id:1,title:"new",status:"in_progress"}]});
current.options.signal.dispatchEvent(new Event("abort"));
await second;
assert.equal(app.todoTasks.value[0].status,"in_progress");
checks.push("F09 local abort leaves task status in_progress");
console.log(JSON.stringify({checks,total:checks.length},null,2));
