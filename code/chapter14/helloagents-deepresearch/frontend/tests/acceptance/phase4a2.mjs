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
const ts=require("typescript"),vue=require("vue"),encoder=new TextEncoder();
const checks=[];
function compile(code,imports=require){
 const module={exports:{}};
 new Function("require","module","exports",ts.transpileModule(code,{compilerOptions:{
  target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText)(imports,module,module.exports);
 return module.exports;
}
const api=compile(fs.readFileSync(path.join(frontend,"src/services/api.ts"),"utf8")
 .replace("import.meta.env.VITE_API_BASE_URL",'"http://fake.invalid"'));
globalThis.requestAnimationFrame=fn=>fn();
globalThis.window={setTimeout:()=>0};
function app(){
 const source=fs.readFileSync(path.join(frontend,"src/App.vue"),"utf8")
  .split('<script lang="ts" setup>')[1].split("</script>")[0];
 return compile(source+
  "\nexport {form,loading,error,todoTasks,progressLogs,handleSubmit,cancelResearch};"+
  "\nexport const status=()=>runStatus.value;export const warnings=()=>runWarnings.value;",
  name=>name==="vue"?{...vue,onBeforeUnmount:()=>{}}:
  name==="./services/api"?api:require(name));
}
const frame=e=>"data: "+JSON.stringify(e)+"\n\n";
async function until(predicate){
 for(let i=0;i<100&&!predicate();i++)await new Promise(resolve=>setTimeout(resolve,1));
 assert.ok(predicate(),"frontend did not reach expected state");
}
async function check(name,fn){
 try{await fn();checks.push({name,ok:true});}
 catch(e){checks.push({name,ok:false,error:e.stack});}
}
for (const completed of [false,true]){
 await check("actual Vue/API AbortSignal, honest text, terminal preservation "+completed,async()=>{
  let body,abortObserved=false;
  globalThis.fetch=async(url,options)=>{
   body=new ReadableStream({start(controller){
    controller.enqueue(encoder.encode(frame({type:"todo_list",run_id:"cancel-run",tasks:[
     {id:1,title:"one",status:completed?"completed":"pending"},{id:2,title:"two",status:"in_progress"}
    ]})));
    options.signal.addEventListener("abort",()=>{
     abortObserved=true;controller.error(new DOMException("transport aborted","AbortError"));
    },{once:true});
   }});
   return new Response(body,{headers:{"content-type":"text/event-stream"}});
  };
  const ui=app();ui.form.topic="fake";const pending=ui.handleSubmit();
  await until(()=>ui.todoTasks.value.length===2);
  ui.cancelResearch();await pending;
  assert.equal(abortObserved,true);
  assert.equal(body.locked,false);
  assert.equal(ui.status(),"cancelled");
  assert.equal(ui.error.value,"");
  assert.equal(ui.loading.value,false);
  assert.equal(ui.todoTasks.value[0].status,completed?"completed":"cancelled");
  assert.equal(ui.todoTasks.value[1].status,"cancelled");
  assert.ok(ui.progressLogs.value.some(t=>t.includes("连接已取消，后台可能仍在收尾")));
  assert.ok(!ui.progressLogs.value.some(t=>/费用.*(停止|结束)|计费.*(停止|结束)|后台.*已经停止/.test(t)));
 });
}
for(const file of ["deadline-events.json","deadline-task-events.json"]){
 await check("actual ASGI deadline events through actual Vue/API "+file,async()=>{
  const data=JSON.parse(fs.readFileSync(path.join(root,"docs/g4a2_evidence",file),"utf8"));
  let body;
  globalThis.fetch=async()=>{
   body=new ReadableStream({start(c){
    c.enqueue(encoder.encode(data.events.map(frame).join("")));c.close();
   }});
   return new Response(body,{headers:{"content-type":"text/event-stream"}});
  };
  const ui=app();ui.form.topic="fake";await ui.handleSubmit();
  assert.equal(ui.status(),"cancelled");
  assert.equal(ui.error.value,"");
  assert.equal(ui.loading.value,false);
  assert.equal(body.locked,false);
  for(const task of ui.todoTasks.value)assert.equal(task.status,"cancelled");
  assert.ok(ui.warnings().some(t=>t.includes("DEADLINE_EXCEEDED")));
 });
}
console.log(JSON.stringify({checks,passed:checks.filter(c=>c.ok).length,
 failed:checks.filter(c=>!c.ok).length},null,2));
if(checks.some(c=>!c.ok))process.exitCode=1;
