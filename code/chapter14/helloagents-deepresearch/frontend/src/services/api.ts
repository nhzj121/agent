const baseURL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
export interface ResearchRequest { topic: string; search_api?: string; }
export interface ResearchStreamEvent { type: string; [key: string]: unknown; }
export interface StreamOptions { signal?: AbortSignal; }
export async function runResearchStream(payload: ResearchRequest,
 onEvent: (event: ResearchStreamEvent) => void, options: StreamOptions = {}): Promise<void> {
 const response = await fetch(baseURL + "/research/stream", {
  method:"POST",headers:{"Content-Type":"application/json",Accept:"text/event-stream"},
  body:JSON.stringify(payload),signal:options.signal});
 if (!response.ok) throw new Error((await response.text().catch(()=>"")) || "研究请求失败：" + response.status);
 if (!response.body) throw new Error("浏览器不支持流式响应");
 const reader=response.body.getReader(),decoder=new TextDecoder("utf-8",{fatal:true});
 let buffer="";
 const dispatch=(raw:string):boolean=>{
  const data=raw.split(/\r?\n/).filter(line=>line.startsWith("data:"))
   .map(line=>line.slice(5).replace(/^ /,"")).join("\n");
  if (!data.trim()) return false;
  let event:ResearchStreamEvent;
  try {event=JSON.parse(data) as ResearchStreamEvent;}
  catch {throw new Error("SSE JSON 解析失败");}
  if (!event || typeof event.type !== "string") throw new Error("SSE 事件缺少 type");
  onEvent(event);
  if (event.type==="error") throw new Error(typeof event.detail==="string"?event.detail:"研究失败");
  return event.type==="done";
 };
 try {
  while(true){
   const {value,done}=await reader.read();
   if(options.signal?.aborted)throw new DOMException("已停止接收","AbortError");
   buffer+=decoder.decode(value||new Uint8Array(),{stream:!done});
   let match:RegExpExecArray|null;
   while((match=/\r?\n\r?\n/.exec(buffer))!==null){
    const frame=buffer.slice(0,match.index);buffer=buffer.slice(match.index+match[0].length);
    if(dispatch(frame))return;
   }
   if(done){
    if(buffer.trim()&&dispatch(buffer))return;
    throw new Error("SSE EOF：未收到 done/error 终止帧");
   }
  }
 } finally {
  try {await reader.cancel();} catch {/* preserve primary error */}
  finally {reader.releaseLock();}
 }
}
