import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import {execFileSync} from "node:child_process";
const frontend=path.resolve(path.dirname(fileURLToPath(import.meta.url)),"../..");
const root=execFileSync("git",["rev-parse","--show-toplevel"],{cwd:frontend,encoding:"utf8"}).trim();
assert.equal(root,"/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source");
process.chdir(root);
const require=createRequire(path.join(frontend,"package.json"));
const ts=require("typescript"),vue=require("vue");
const encoder=new TextEncoder(),checks=[];
function compile(code,imports=require){
 const module={exports:{}};
 new Function("require","module","exports",ts.transpileModule(code,{compilerOptions:{
  target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText)(
  imports,module,module.exports);
 return module.exports;
}
const api=compile(fs.readFileSync(path.join(frontend,"src/services/api.ts"),"utf8")
 .replace("import.meta.env.VITE_API_BASE_URL",'"http://fake.invalid"'));
async function check(name,fn){try{await fn();checks.push({name,ok:true});}catch(e){
 checks.push({name,ok:false,error:e.stack});}}
function response(bytes,hold=false){
 let stream;
 globalThis.fetch=async()=>{stream=new ReadableStream({start(c){
  for(const item of bytes)c.enqueue(typeof item==="string"?encoder.encode(item):item);
  if(!hold)c.close();
 }});return new Response(stream,{headers:{"content-type":"text/event-stream"}});};
 return ()=>stream;
}
globalThis.requestAnimationFrame=fn=>fn();
globalThis.window={setTimeout:()=>0};
function harness(realApi=false){
 const requests=[];let unmount;
 const source=fs.readFileSync(path.join(frontend,"src/App.vue"),"utf8")
 .split('<script lang="ts" setup>')[1].split("</script>")[0];
 const exports=compile(source+
 "\nexport {form,loading,error,todoTasks,reportMarkdown,progressLogs,handleSubmit,startNewResearch,cancelResearch,formatTaskStatus};"+
 "\nexport const state=()=>({runStatus:typeof runStatus==='undefined'?undefined:runStatus.value,tasks:todoTasks.value,report:reportMarkdown.value,reportNoteId:reportNoteId.value,reportNoteStatus:reportNoteStatus.value});",
 name=>name==="vue"?{...vue,onBeforeUnmount:fn=>{unmount=fn;}}:
 name==="./services/api"?(realApi?api:{runResearchStream:(payload,onEvent,options)=>
 new Promise((resolve,reject)=>requests.push({payload,onEvent,options,resolve,reject}))}):require(name));
 return {app:exports,requests,unmount:()=>unmount?.()};
}
const frame=event=>"data: "+JSON.stringify(event)+"\n\n";
await check("UTF8 byte boundaries + reader release",async()=>{
 const bytes=encoder.encode(frame({type:"status",message:"中文"})+frame({type:"done"}));
 const get=response([...bytes].map(b=>new Uint8Array([b]))),events=[];
 await api.runResearchStream({topic:"x"},e=>events.push(e));
 assert.deepEqual(events.map(e=>e.type),["status","done"]);
 assert.equal(events[0].message,"中文");assert.equal(get().locked,false);
});
await check("EOF rejects even after final_report",async()=>{
 for(const event of [{type:"status"},{type:"final_report",report:"draft"}]){
  const get=response([frame(event)]);
  await assert.rejects(api.runResearchStream({topic:"x"},()=>{}),/EOF|终止|结束/);
  assert.equal(get().locked,false);
 }
});
await check("callback errors propagate",async()=>{
 const get=response([frame({type:"status"})+frame({type:"done"})]);
 await assert.rejects(api.runResearchStream({topic:"x"},()=>{throw new Error("UI failure");}),/UI failure/);
 assert.equal(get().locked,false);
});
await check("malformed JSON rejects",async()=>{
 const get=response(['data: {bad}\n\n'+frame({type:"done"})]);
 await assert.rejects(api.runResearchStream({topic:"x"},()=>{}));assert.equal(get().locked,false);
});
await check("error frame reaches UI and rejects",async()=>{
 const get=response([frame({type:"error",detail:"research failed"})]),events=[];
 await assert.rejects(api.runResearchStream({topic:"x"},e=>events.push(e)),/research failed/);
 assert.equal(events[0].type,"error");assert.equal(get().locked,false);
});
await check("done releases unfinished response",async()=>{
 const get=response([frame({type:"done"})],true);
 await api.runResearchStream({topic:"x"},()=>{});assert.equal(get().locked,false);
});
await check("CRLF framing",async()=>{
 response([(frame({type:"status"})+frame({type:"done"})).replaceAll("\n","\r\n")]);
 const events=[];await api.runResearchStream({topic:"x"},e=>events.push(e));
 assert.deepEqual(events.map(e=>e.type),["status","done"]);
});
await check("AbortSignal propagation",async()=>{
 const controller=new AbortController();let signal;
 globalThis.fetch=async(url,options)=>{signal=options.signal;return new Promise((resolve,reject)=>
  signal.addEventListener("abort",()=>reject(new DOMException("stop","AbortError")),{once:true}));};
 const pending=api.runResearchStream({topic:"x"},()=>{},{signal:controller.signal});
 controller.abort();await assert.rejects(pending,{name:"AbortError"});assert.equal(signal,controller.signal);
});
await check("Planner buffers + run/event deduplication",async()=>{
 const {app,requests}=harness();app.form.topic="x";const done=app.handleSubmit();const req=requests[0];
 const event={type:"tool_call",run_id:"r",event_id:1,task_id:1,tool:"note",agent:"planner",
  parameters:{action:"read"},success:true,note_status:"saved",note_id:"note_1",result:"ok"};
 req.onEvent(event);req.onEvent(event);
 req.onEvent({type:"todo_list",run_id:"r",tasks:[{id:1,title:"t"}]});
 assert.equal(app.todoTasks.value[0].toolCalls.length,1);
 assert.equal(app.todoTasks.value[0].noteId,"note_1");
 req.onEvent({type:"final_report",run_id:"r",report:"report",run_status:"completed"});
 req.onEvent({type:"done",run_id:"r",run_status:"completed"});req.resolve();await done;
});
await check("late event/catch/finally isolation",async()=>{
 const {app,requests}=harness();app.form.topic="A";const first=app.handleSubmit();
 const old=requests[0];app.startNewResearch();app.form.topic="B";const second=app.handleSubmit();
 old.onEvent({type:"error",run_id:"old",detail:"old error"});
 old.onEvent({type:"final_report",report:"old report"});
 old.reject(new Error("late old failure"));await first;
 assert.equal(app.loading.value,true);assert.equal(app.error.value,"");assert.equal(app.reportMarkdown.value,"");
 const current=requests[1];current.onEvent({type:"final_report",run_id:"new",report:"new report"});
 current.onEvent({type:"done",run_id:"new",run_status:"completed"});current.resolve();await second;
 assert.equal(app.reportMarkdown.value,"new report");assert.equal(app.loading.value,false);
});
await check("task terminal status/error cannot regress",async()=>{
 const {app,requests}=harness();app.form.topic="x";const pending=app.handleSubmit(),req=requests[0];
 req.onEvent({type:"todo_list",tasks:[{id:1,title:"t"}]});
 req.onEvent({type:"task_status",task_id:1,status:"failed",detail:"search failed"});
 req.onEvent({type:"task_status",task_id:1,status:"in_progress"});
 assert.equal(app.todoTasks.value[0].status,"failed");
 assert.ok(app.todoTasks.value[0].notices.includes("search failed"));
 assert.equal(app.formatTaskStatus("failed"),"失败");assert.equal(app.formatTaskStatus("cancelled"),"已取消");
 req.onEvent({type:"final_report",report:"partial",run_status:"failed"});
 req.onEvent({type:"done",run_status:"failed"});req.resolve();await pending;
 assert.equal(app.state().runStatus,"failed");
});
await check("cancel marks only unfinished local tasks",async()=>{
 const {app,requests}=harness();app.form.topic="x";const pending=app.handleSubmit(),req=requests[0];
 req.onEvent({type:"todo_list",tasks:[{id:1,status:"completed"},{id:2,status:"in_progress"}]});
 app.cancelResearch();req.reject(new DOMException("stop","AbortError"));await pending;
 assert.equal(app.todoTasks.value[0].status,"completed");assert.equal(app.todoTasks.value[1].status,"cancelled");
 assert.equal(app.state().runStatus,"cancelled");
});
for(const [file,paused] of [["fake-workflow.json",false],["fake-paused.json",true]]){
 await check("actual API + Vue + backend fixture "+file,async()=>{
  const fixture=JSON.parse(fs.readFileSync(path.join(root,"docs/g3_evidence",file),"utf8"));
  response([fixture.events.map(frame).join("")]);
  const {app}=harness(true);app.form.topic="fixture";await app.handleSubmit();
  assert.equal(app.error.value,"");assert.equal(app.state().runStatus,fixture.expected.run_status);
  assert.equal(app.reportMarkdown.value,fixture.expected.report);
  assert.equal(app.state().reportNoteId,fixture.expected.note_id);
  assert.equal(app.state().reportNoteStatus,fixture.expected.report_note_status);
  const task=app.todoTasks.value[0],expected=fixture.expected.tasks[0];
  assert.equal(task.status,expected.status);assert.equal(task.summary,expected.summary);
  assert.equal(task.noteStatus,expected.note_status);assert.equal(task.noteId,expected.note_id);
  if(paused)assert.ok(task.notices.some(x=>x.includes("WRITES_PAUSED")||x.includes("笔记")));
  else assert.equal(task.toolCalls.filter(x=>x.tool==="note").length,2);
 });
}
await check("reader read error and malformed UTF8 release locks",async()=>{
 for (const invalid of [true,false]) {
  let stream;
  globalThis.fetch=async()=>{
   stream=new ReadableStream({start(controller){
    if(invalid) {controller.enqueue(new Uint8Array([255]));controller.close();}
    else controller.error(new Error("read failure"));
   }});
   return new Response(stream);
  };
  await assert.rejects(api.runResearchStream({topic:"x"},()=>{}));
  assert.equal(stream.locked,false);
 }
});
await check("unmount prevents late events and finalizers",async()=>{
 const {app,requests,unmount}=harness();app.form.topic="x";const pending=app.handleSubmit();
 unmount();requests[0].onEvent({type:"error",detail:"late"});
 requests[0].reject(new DOMException("stop","AbortError"));await pending;
 assert.equal(app.error.value,"");
});
await check("failed tool metadata never attaches counterfeit ID",async()=>{
 const {app,requests}=harness();app.form.topic="x";const pending=app.handleSubmit(),req=requests[0];
 req.onEvent({type:"todo_list",tasks:[{id:1,title:"t"}]});
 req.onEvent({type:"tool_call",event_id:1,task_id:1,success:false,
   note_id:"forged",note_path:"/forged",note_status:"error",error_code:"IO_ERROR",detail:"disk"});
 assert.equal(app.todoTasks.value[0].noteId,null);
 assert.equal(app.todoTasks.value[0].toolCalls[0].noteId,null);
 req.onEvent({type:"final_report",report:"report",run_status:"completed"});
 req.onEvent({type:"done",run_status:"completed"});req.resolve();await pending;
});
console.log(JSON.stringify({checks,passed:checks.filter(x=>x.ok).length,
 failed:checks.filter(x=>!x.ok).length},null,2));
if(checks.some(x=>!x.ok))process.exitCode=1;
