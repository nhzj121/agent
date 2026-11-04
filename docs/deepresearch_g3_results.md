# G3 事件、API 与前端一致性实施结果

日期：2026-11-03（Asia/Shanghai）。

**结论：G3 后端 17 项、前端 17 项通过；G0 15 项、G1 14 项、G2a 23 项、G2b 29 项回归通过，均无跳过。Vue 类型检查与生产构建通过。满足进入 G4a.1 的前置条件，本阶段到此停止。**

## 1. 基线与范围

全部项目操作通过 WSL Ubuntu22.04.3 的 Linux 工具链执行，每次先核对 Git 根目录为 /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source。Git main / 755ae75958e6fb072c8a075bcbc55ad15d98bb17。

开始记录 251 个原有文件指纹，保留已有 G0/G1/G2a/G2b、用户 README/Zone.Identifier、AGENTS.md 和所有未跟踪资料。未安装/升级依赖，后端 pyproject/uv.lock、前端 package.json/package-lock.json、所有历史报告和 G2b 版本/归属模块、Repository 均未改变。未暂存、提交、推送或清理用户文件。

证据：[baseline.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/baseline.json)、[integrity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/integrity.json)。所有笔记测试仅使用 TemporaryDirectory 和合成数据，模型/搜索均为 Fake，未访问、切换或迁移真实笔记。没有修改 HelloAgents 核心循环、共享 LLM/SearchTool、G2b 凭据授权或 ETag 校验。

## 2. 修改文件

B 为 code/chapter14/helloagents-deepresearch/backend；F 为同级 frontend。

| 文件 | 修改原因 |
|---|---|
| [services/tool_events.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/tool_events.py) | 锁内 ID 分配/append；结构化结果与可信 scope 解析；单一归属 cursor；live/drain 的 ack、inflight 和失败补发 |
| [services/agent_adapter.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/agent_adapter.py) | 原监听器安全投影附带服务端 NoteToolResult/NoteScope，不再在 Tracker 从文本猜成功 |
| [models.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/models.py) | 增量任务 error/detail、note_status/error/etag；研究 run_id/run_status/warnings；最终笔记状态 |
| [agent.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py) | 每 run 身份与重入保护；同步/流式失败一致；Worker 启动失败收尾；Queue 交接；汇总任务状态与笔记告警 |
| [services/reporter.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/reporter.py) | prompt 明确研究、任务错误及笔记状态，保留原正文/GeneratedText 版本绑定 |
| [main.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/main.py) | 增量 HTTP 状态；显式 agent_factory 注入测试；SSE 错误帧及本层迭代器 finally 关闭 |
| [api.ts](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/frontend/src/services/api.ts) | EOF/JSON/type/UTF-8 协议错误、callback 错误传播、reader cancel/release；兼容 LF/CRLF |
| [App.vue](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/frontend/src/App.vue) | 请求身份隔离、早到事件缓冲、run/event 去重、终态保护、独立笔记告警、任务/报告笔记展示 |
| [G1 测试](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_1_core.py)、[G2b 归属测试](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_2b_ownership.py) | 将旧的精确字段集合断言改为保留原字段子集并新增 run 身份/状态断言，适配已授权的增量协议 |
| [test_phase_3_events.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_3_events.py)（新增） | 8 项 Tracker 并发、投递和结构化状态测试 |
| [test_phase_3_http.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_3_http.py)（新增） | 9 项真实 API/Fake 工作流、失败、重入与故障交接测试 |
| [phase3.mjs](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/frontend/tests/acceptance/phase3.mjs)（新增） | 17 项实际 API/SFC 源码编译后的前端契约测试 |
| 本报告、g3_evidence/（新增） | 命令、失败输出、回归、完整 Fake 事件样本和范围核验 |

Planner → Search → Summarizer → Reporter 主流程、Queue、Tracker 的 record/drain/即时 sink 机制保留。

## 3. Tracker 并发与交接机制

### 3.1 事件与可信归属

ToolCallEvent.id 在同一锁内分配并 append，event_id 仍为整数。新增 run_id/stage/success/error_code/detail/note_etag/note_status/persisted，不重命名旧字段。

只接受服务端 NoteToolResult + NoteScope 作为结构化来源，模型 JSON 不能伪造这些 Python 对象。task_id 来自可信执行 scope 或工具验证后的任务快照；Reporter 的 note.read 只有 note_id 时，仍从已验证结果关联真实任务。失败不使用模型参数里的 note_id，不从 ID:、表情、标题或 tags 猜成功/归属。

Planner 尚无可验证任务身份的事件保持未关联；不把标题中的“任务 1”猜成任务授权。对于具有有效 task_id、但早于 todo_list 到达的工具事件，前端先缓冲，列表到达后关联并按 run_id/event_id 去重。

旧 NoteTool 字符串仍可记日志，但标为 UNVERIFIED_TOOL_RESULT，不能回填可信笔记链接。相关问题以研究告警可见，不把未知结果伪装为保存成功。

### 3.2 投递与归属分离

- _cursor 仅控制状态归属回填，在 Tracker 锁内串行应用；callback 不递归 drain。
- _inflight 标识正在 callback 或已被流式 drain 领取的事件；_delivered 标识已确认交接。
- record 在锁内读取 sink/登记 inflight，锁外 callback。只有 callback 成功或 Queue.put 成功才 ack；失败释放 claim，journal 仍保留，后续 drain 可补发。
- 同步 drain 默认消费；流式 drain 先领取，Queue 入队/主生成器实际转发时确认。
- 多 Worker drain 取到别的任务事件时，不覆盖事件的可信 task_id。
- 正常生产者结束并 join 后才关闭 sink。线程启动失败直接产生一次 failed 终态和内部完成标记，避免等待不存在的 Worker 或 join 未启动线程。

故障测试先写后修：原实现确实存在 ID 竞争、callback 失败未保留、交接时不能区分 inflight/已投递等问题。正常生产流此前没有被认定为必然重复；本阶段验证正常事件仍只发布一次，只对已测故障边界增加局部确认状态，没有替换事件总线。

本地确认不等于网络端到端恰好一次。callback 若在入队成功后再抛错，可能补发同一个 run/event ID；前端幂等去重。无持久化回放、无断线重连恢复保证。

## 4. 任务、笔记、研究状态

| 层次 | 语义 |
|---|---|
| task.status | pending/in_progress/completed/skipped/failed/cancelled；描述研究任务执行 |
| task.note_status | disabled/not_started/saved/error/conflict/paused；独立描述笔记保存/验证 |
| task.note_error | code/detail/persisted；失败不隐藏总结、不制造成功 ID |
| run_status | running/completed/partial/failed/cancelled；done 只是协议正常结束 |
| report_note_status/error | 最终报告正文和其落盘状态分开 |
| note_etag | 仅展示已验证快照版本，不向 G2b 写入凭据反向授权 |

部分任务成功、其他失败/跳过时 partial；所有任务都没有成功总结（包括全 skipped）为 failed，即使 Reporter 返回文字也不标成 completed。全部研究任务成功但笔记暂停/失败时，研究可 completed，同时显示 note_status 和 warnings。

同步执行现在捕获任务级搜索/总结异常，将对象标为 failed 后继续 Reporter，返回 HTTP 200 + partial/failed 结果；SSE 同样表达。规划/报告等研究级致命异常仍走 HTTP 500 或 HTTP 200 之后的 error 帧；配置错误保持 400，请求校验保持原 FastAPI 行为。

成功读取可建立真实笔记映射，但不会清除先前失败写入的 conflict/error/paused；后续成功写入才恢复 saved。错误详细信息同时进入任务 notices 和研究 warnings。任务终态不会被前端迟到的 in_progress/chunk 改回进行中或覆盖总结。

每次 run 新建 run_id 并 reset Tracker，旧 Worker 收尾期间同一 Agent 拒绝重入。显式 Repository 的 run 身份与该 run_id 一致；Agent 复用后关闭笔记会清除旧 owner/绑定，不沿用上一研究笔记。

## 5. 最终报告与 G2b 安全边界

G2b ReadReceipt/GenerationBasis、LocalLLMView 冻结规则、NoteOwnership 和 Repository 的版本/幂等实现未改。Tracker/前端的 note_etag、note_id 只用于展示和关联，不会替换模型生成时的 ETag。

最终报告持久化进一步要求 owner.run_id == state.run_id，仍由 run_id + final_report 幂等身份定位；不从任务 conclusion 或标题猜测。持久化后 report_note/final_report 关联当前 run 的同一真实笔记。失败只返回报告正文、错误和告警，不回填虚假路径。

**重要兼容收紧：** 未显式注入 Repository 时，旧 NoteTool 没有可验证 run/purpose，最终报告不再沿旧标题/结论规则写入，明确报告 OWNERSHIP_ERROR。旧工具调用结果也不再被推断为可信保存成功。这不是迁移或自动切换；需要持久化新安全报告的调用者继续使用 G2b 的显式 note_repository 注入。ENABLE_NOTES=false 返回 disabled。

Task/Reporter 的工具视图、工具名称和主要动作不变；笔记失败不会增加额外 LLM 调用或转换成研究任务 failed。

## 6. HTTP/SSE 与前端

HTTP 路径 /healthz、/research、/research/stream 及 topic/search_api 不变。响应保留 report_markdown/todo_items，增量返回 run_id/run_status/warnings、任务错误与笔记状态、最终报告笔记字段。

SSE 保留 status/todo_list/task_status/sources/task_summary_chunk/tool_call/report_note/final_report/done/error。final_report 增加最终 tasks 快照、warnings、report_note_status/error；done 带 run_status。事件 run_id 保持同一研究身份。

main 的 SSE 生成器 finally 显式关闭本层拥有的研究迭代器；发生研究异常后发 error/detail/run_status=failed，不伪造 done。仍为原同步 StreamingResponse 方式，没有增加异步 disconnect 桥接或传输层取消。

前端：

- API 遇 EOF 而无合法 done/error 必须失败；只有 final_report 不足以证明协议完成。
- JSON/type/UTF-8 错误和 UI callback 异常均传播；error 帧先交给 UI，再作为失败 reject。
- 终止、读取失败、解析失败、callback 失败都 cancel/release reader。清理错误不遮盖主异常。
- 支持现有 LF、任意 UTF-8 字节切分，另兼容 CRLF。
- onEvent、await 后处理、catch、finally 均核对当前 AbortController。旧请求不能污染新任务、错误、报告或 loading；组件卸载、旧动画/复制路径回调也有身份边界。
- 工具事件按 run/event 去重，Planner 早到事件暂存再关联。失败记录不附着伪造 ID。
- UI 展示 completed/skipped/failed/cancelled 中文状态、成功数和已终结数；任务笔记及报告笔记分别显示状态/路径/告警，failed.detail 可见。
- 取消只停止接收并将未终结的本地任务标 cancelled，保留已经 completed 的任务。提示后台研究可能仍继续；不宣称同步模型/搜索调用已被强制停止。

## 7. 先复现与真实验收结果

### 7.1 初始失败

后端测试先写再改：13 项初始为 failures=5、errors=8，退出 1，[before.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/before.stderr.txt)。包含并发重复 ID、失败伪 ID、read 关联、callback 失败/交接；HTTP 部分错误来自尚未提供 agent_factory 测试接线入口，不能全部冒充原业务 Bug。

前端初始 14 检查为 1 通过、13 失败：[frontend-before.stdout.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/frontend-before.stdout.json)。其中两项因完整工作流样本尚未生成；原 LF/UTF-8 解码本身已有支持，该组合检查主要失败于 reader 未释放，未声称此前 UTF-8 不可用。

历史回归首次：G1 的三处和 G2b 的一处失败来自精确字段快照拒绝新增 run_id/run_status。保留旧字段、状态、顺序断言，改成兼容子集并新增新字段断言；没有跳过/删除失败测试。旧日志：[g1-first.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g1-first.stderr.txt)、[g2b-first.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g2b-first.stderr.txt)。历史阶段报告、当时证据和验收结论未改写。

### 7.2 最终结果

| 检查 | 实际结果 |
|---|---|
| G3 Python | 17 tests，0.419 秒，OK，退出 0 |
| G3 前端源码契约 | 17 checks，全部通过，退出 0 |
| G0 | 15 tests，14.648 秒，OK，退出 0 |
| G1 | 14 tests，0.040 秒，OK，退出 0 |
| G2a | 23 tests，4.685 秒，OK，退出 0 |
| G2b | 29 tests，1.667 秒，OK，退出 0 |
| vue-tsc --noEmit | 退出 0 |
| Vite 生产构建 | 退出 0 |
| git diff --check / 暂存 | 通过，无暂存修改 |

全部无跳过。ERROR/WARNING 日志包括预期失败注入，不是被忽略的断言失败。既存 FastAPI on_event/构建许可证弃用提示未借机改造；Vite 提示输出目录在前端根之外、不自动清空，属于有意隔离构建产物。

后端日志：[g3.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g3.stderr.txt)；前端：[frontend-final.stdout.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/frontend-final.stdout.json)；回归：[g0.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g0.stderr.txt)、[g1.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g1.stderr.txt)、[g2a.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g2a.stderr.txt)、[g2b.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g2b.stderr.txt)。类型/构建：[typecheck.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/typecheck.json)、[frontend-build.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/frontend-build.txt)。

关键故障实测：20 并发分配唯一 ID；正常 live 事件一次；sink 在 put 前失败可补发一次；inflight 关闭失败后仍可 drain；两个真实 Worker 中一次 Queue.put 失败，事件不串任务、不重复；线程启动失败终态一次、无等待挂起；同 Agent 活跃研究拒绝重入。

G0 重新在 venv/g0-pvxz77bm 构建 wheel/sdist、创建空环境、安装/检查依赖与新 wheel、Fake HTTP 和三种 Uvicorn 启动健康检查，全部通过。未借用原 backend/.venv 手工包。证据：[g0-commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g0-commands.json)、[g0-setup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g0-setup.json)、[g0-installed-environment.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g0-installed-environment.json)、[g0-http-smoke.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g0-http-smoke.json)，完整日志位于 g3_evidence/g0-logs/。

前端构建输出在独立 venv/g3-front-2zeht18s/dist，未覆盖前端原 dist 或清空用户目录。

## 8. 完整显式 Repository Fake 链路

[正常工作流样本](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/fake-workflow.json) 与 [暂停写入样本](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/fake-paused.json) 来自真实 FastAPI TestClient + DeepResearchAgent + 真实 HelloAgents/ProjectToolAwareAgent + 临时 FileRepository，模型/搜索为 Fake。

正常流程：
Planner 规划 → Search → Task create → 总结 → Reporter 仅用 note_id read 任务、create 报告 → 最终生成 → 按原冻结基线 persist 同一报告。Backend 验证每个 run 只有任务笔记和一份 final_report、归属正确，reporter read 事件关联 task_id=1，没有跨 run 混用。

暂停流程：
任务 create 和报告 create/persist 被拒绝，仍返回 task-summary/final-report；task.status=completed、note_status=paused，报告笔记 paused、note_id=None，告警存在。未把笔记失败变成研究任务失败。

随后把实际 SSE 字节经真实 api.ts 解析器送入编译后的真实 App.vue setup 逻辑和 Vue 响应式状态，验证任务总结、任务笔记 ID/状态、Reporter read 记录、报告笔记 ID/状态和 run_status 一致。不是仅检查源码字符串。没有真实浏览器 DOM/视觉 E2E，也没有真实模型质量测试。

## 9. 复跑命令

在指定 WSL 仓库内执行，各阶段独立运行：

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G3_ROOT="$PWD"
G3_PY="$G3_ROOT/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"
G3_NODE=/home/nhzj121/.nvm/versions/node/v24.15.0/bin/node
G3_FRONT="$G3_ROOT/code/chapter14/helloagents-deepresearch/frontend"

"$G3_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_3*.py' -v
"$G3_NODE" "$G3_FRONT/tests/acceptance/phase3.mjs"
"$G3_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_1*.py' -v
"$G3_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2a*.py' -v
"$G3_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2b*.py' -v

G0_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
env -u G0_WORK_ROOT -u PYTHONPATH -u VIRTUAL_ENV \
  G0_BASE_PYTHON="$G0_BASE" G0_UV=/home/nhzj121/.local/bin/uv \
  "$G0_BASE" -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v

(
  cd "$G3_FRONT" &&
  test "$(git rev-parse --show-toplevel)" = "$G3_ROOT" &&
  "$G3_NODE" node_modules/vue-tsc/bin/vue-tsc.js --noEmit
)
~~~

先运行 Python G3 生成完整 Fake 样本，再执行前端契约测试。构建重跑使用新的独立输出目录，不复用/清空原产物；本次精确 argv、cwd 和输出目录见 [frontend-build.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/frontend-build.json)。其余精确命令：[g3.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g3.json)、[frontend-final.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/frontend-final.json)、[g0.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g0.json)、[g1.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g1.json)、[g2a.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g2a.json)、[g2b.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g3_evidence/g2b.json)。

## 10. 限制、回滚与 G4a.1 前置条件

- 无 Worker 池、并发准入上限、deadline 或模型/搜索超时；同实例重入保护不等于全局容量控制。
- 无 HTTP disconnect 取消传播。关闭研究迭代器仍可能等待原 Worker join，后台同步请求可能继续；前端 cancelled 是本地接收状态。
- Tracker/事件为进程内内存，不提供持久化回放或端到端恰好一次；关闭客户端后的不可达事件不承诺送达。
- 新安全存储仍需显式 Repository 注入。真实工作区未启用/迁移，旧 NoteTool 的已知存储风险未因状态展示而消失；不可验证结果不授予可信笔记关联或最终报告写入。
- G2a 普通编辑剩余竞争、G2b 语义合并限制、真实模型质量与真实网络行为仍不在本次证明范围。
- G5 依赖漏洞治理未执行，不以本次构建通过替代其验收。

回滚应将 G3 前后端作为一组回退，保留 G2 安全存储/版本绑定、所有候选笔记和用户修改，不通过旧快照覆盖新数据，不清理未跟踪审计文档。若没有安全接线可用，选择 ENABLE_NOTES=false，不能回退成“旧工具失败但 UI 静默成功”。

事件、状态、API、前端一致性和全部回归通过，没有发现阻碍进入 G4a.1 的 G3 遗留问题。下一阶段必须等待指令；本阶段完成后停止，不提前实施 G4a 或后续阶段。
