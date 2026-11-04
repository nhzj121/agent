# DeepResearch G4a.2 HTTP 断连与 SSE 取消传播实施结果

日期：2026-11-04（Asia/Shanghai）。

**G4a.2 完成。新增后端 27 项、前端 4 项验收全部通过；G0/G1/G2a/G2b/G3/G4a.1 全部回归通过，Vue 类型检查与生产构建通过，均无跳过。满足进入 G5 发布验收准备的执行与传输层前置条件；尚不能据此宣称已通过生产发布验收。**

## 1. 基线与改动范围

全部项目操作在 WSL 注册发行版 Ubuntu22.04.3 的 Linux 仓库 /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source 中执行，命令先核对 Git 根目录。基线 main / 2447fc91d41b3a46a7a4896d216355fad84abbfa，已有 G0–G4a.1 代码和文档已在此前任务中提交。本阶段没有暂存、提交、推送、拉取或清理用户文件，未跟踪的 README (2).md:Zone.Identifier 保留。

实施前保存 419 个相关已跟踪文件的指纹；其中只有下表 6 个原有文件改变。新增内容均为本阶段桥接模块、验收与报告/证据。证据：[baseline.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/baseline.json)、[integrity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/integrity.json)。

| 文件 | 修改与理由 |
|---|---|
| [services/sse_bridge.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/sse_bridge.py:26)（新增） | 后台研究线程、传输监督线程、有界异步交接、ASGI receive/send/deadline 生命周期；SSE 与 JSON 两种响应外观 |
| [main.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/main.py:156) | 共用原进程准入/初始化，向桥接层注入实际研究迭代器和取消快照；保留同步 JSON 字段与错误状态 |
| [agent.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:230) | 在既定控制锁内生成一致取消快照；迟到异常保留 cancelled；正常 done 后关闭迭代器不改成取消 |
| [execution_control.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/execution_control.py:94) | retain 增加 allow_cancelled=False 默认参数；桥接清理可登记生命周期引用，Worker 的默认准入/取消检查不变 |
| [App.vue](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/frontend/src/App.vue) | 合法 cancelled 终止帧允许没有最终报告；Abort 文案改为“连接已取消，后台可能仍在收尾” |
| [G0 验收](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_0_environment.py) | 将 services.sse_bridge 纳入 wheel/sdist/独立安装导入断言，不削弱原断言 |
| [G4a.1 报告](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/deepresearch_g4a1_results.md:151) | 仅修正 G4_PY、G4_FRONT 两处路径变量拼接 |
| [test_phase_4a_2_disconnect.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_4a_2_disconnect.py)（新增） | 26 项实际 ASGI、状态、容量、提交锁、线程失败、迭代器与终态验收 |
| [test_phase_4a_2_sdk.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_4a_2_sdk.py)（新增） | 1 项真实 OpenAI/HTTPX MockTransport 经实际 ASGI 断连的响应/共享客户端验收 |
| [phase4a2.mjs](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/frontend/tests/acceptance/phase4a2.mjs)（新增） | 4 项实际 api.ts/Vue 源码编译执行的 Abort、终态及后端 deadline 事件联测 |
| 本报告、docs/g4a2_evidence/（新增） | 初始失败、竞争复现、实际执行命令、回归输出和范围指纹 |

没有修改依赖声明、锁文件、HelloAgents 核心循环、原 Queue/Tracker、G2a Repository、G2b ReadReceipt/GenerationBasis/归属协议或真实笔记。Planner → Search → Summarizer → Reporter 保留。

笔记实验全部使用 TemporaryDirectory 与合成数据，显式注入 Repository；模型/搜索为 Fake 或受控 MockTransport。测试阻断外部 socket/DNS；G0 仅允许已有受控本机健康检查。没有真实收费请求。

## 2. 架构和线程边界

~~~mermaid
flowchart LR
  ASGI["ASGI 事件循环：receive / send / deadline"] -->|"关闭或取消意图"| SUP["传输监督线程"]
  SUP -->|"cancel + 已有提交锁"| CTRL["同一个 ExecutionControl"]
  PROD["研究迭代器所属后台线程"] -->|"容量 32 的异步交接"| ASGI
  PROD --> PLAN["Planner → 有界任务 Worker → Reporter"]
  CTRL -->|"协作检查点"| PLAN
  PLAN -->|"实际完成后释放引用"| CTRL
  SUP -->|"收尾后释放引用"| CTRL
  PROD -->|"close 后释放引用"| CTRL
~~~

FastAPI 路由仍在其同步初始化线程内构造配置和 Agent，并在实际研究开始前取得原进程准入。响应接入 ASGI 后，ResearchBridge 只由一个后台 producer 线程推进和关闭研究迭代器。同步入口的 run() 也在这个后台线程执行；主线程不会因 Planner/Reporter 的同步调用卡在 next() 中。

传输监督线程先启动，等待响应完成/断连/deadline 的通知。它负责取得既有控制锁、接受取消并生成快照。该设计是必要的：NoteTool 已进入原子提交时可能持有控制锁；ASGI 直接调用 control.cancel() 也会等待这把锁，导致断连请求无法及时退出。此等待现在只发生在后台。

新增的容量 32 asyncio.Queue 仅为研究线程到 ASGI 的交接通道，不替换原任务 Queue 或 Tracker。producer 通过 run_coroutine_threadsafe 交付数据，在其所属线程等待队列空间，每 0.05 秒检查传输关闭；事件循环只 await asyncio.Queue.get。队列满时断开，挂起的 put 会取消，迭代器由 producer 关闭，内存不随流片段无限增长。

实际业务 Worker 仍由 G4a.1 调度；阻塞模型、搜索、同步 Queue.get、thread.join 和 SDK 响应关闭都不会搬到 ASGI 事件循环。验收同时用线程标识、事件循环心跳及同步 Queue.get/Thread.join 的运行断言检查这一点。

## 3. 断连检测与取消传播

[响应生命周期](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/sse_bridge.py:225) 同时运行三项异步工作：

1. 发送 SSE/JSON 响应。
2. 唯一 receive 消费者监听 http.disconnect。
3. 每至多 0.05 秒检查剩余单调 deadline；研究已经产生终止帧后不再用研究 deadline 取消正常传输收尾。

ASGI 2.3 和 2.4 都使用这条监听路径。2.4 不依赖“必须出现下一个 chunk 才能在 send 中发现断开”；Planner/Reporter 无输出时仍可接收 disconnect。send 抛 OSError、响应头发送失败、ASGI 请求任务被取消、未正常结束的响应迭代器关闭，均进入同一个关闭入口。

未完成研究的传输关闭产生 CLIENT_DISCONNECTED。桥接先停止向连接交付新数据，并通知已运行的监督线程；监督线程随后调用当前研究原来的 ExecutionControl.cancel。没有创建替代上下文，也没有只关前端 reader 而遗漏执行层信号。

ASGI 请求立即取消自身发送/监听任务并关闭自己拥有的异步迭代器，不 join producer 或 Worker。客户端已断开时不尝试保证 cancelled 帧送达；监督线程和 provider 可以继续收尾。

### 3.1 取消原因与关闭顺序

测试发现：producer 先关闭 Agent 迭代器，会触发 GeneratorExit，把通用 CANCELLED 抢先写入上下文。修复后 producer 在后台等待监督线程接受第一取消原因，再关闭所属迭代器。这个等待不发生在事件循环，也不会提前释放容量。可控屏障测试证明 CLIENT_DISCONNECTED 不会被通用关闭原因抢占。

### 3.2 正常 done 后释放 reader

api.ts 在读到 done 后正常释放 reader。此时连接关闭不应把已完成研究改成 cancelled。桥接记录研究已产生终止结果，按正常传输收尾处理；Agent 也在已经 yield done 后的 GeneratorExit 路径保留原研究状态。研究容量仍等实际清理完成才回收。该路径有先失败后修复的独立验收，不能只测试用户中途 Abort。

## 4. 引用、容量与取消状态

桥接构造时，为 producer 和监督线程各保留一个生命周期引用，加上原执行入口引用及 G4a.1 已启动 Worker 的引用。初始化/启动失败、从未推进业务的响应头失败也分别回收这些保留引用。

| 所属对象 | 何时释放 |
|---|---|
| 原执行入口 | finish() 幂等释放；它不再单独代表所有后台工作已经结束 |
| producer | 所属研究迭代器关闭、本线程清理与交接退出后 |
| 任务 Worker | 同步 provider 返回、该 Worker 响应与生成器清理后，沿用 G4a.1 |
| 传输监督线程 | 接受取消、处理快照并完成自身清理后 |

总引用为零时才触发原运行锁和准入租约的释放。请求返回不是回收容量的依据。cleanup_pending 描述的是仍未达到 idle 的后台生命周期；没有新增持久化任务登记表或公开状态 API。

实测 provider 继续阻塞时，HTTP 请求已经退出，但研究容量仍占用、同一 Agent 仍拒绝重入。放行 provider 后才回到 idle 并恢复容量。阻塞 SDK 流只由其实际所属线程关闭，共享客户端和其他请求保持可用。

[cancellation_snapshot](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:230) 在已有控制锁内将未终结任务标 cancelled，保留 completed/skipped/failed；冻结任务快照和 done。迟到 provider 异常也不能把 cancelled 研究改回 failed。桥接停止后丢弃普通排队事件，deadline 终态发出后不再排回旧 in_progress/completed 事件。

取消与 NoteTool 提交继续使用 G4a.1 同一把锁：取消被接受前已经进入的提交可以完成，内容保留；之后的新提交/模型轮次/任务由既有检查点拒绝。没有读取最新 ETag 替换模型冻结版本，生命周期引用也不是写入授权。

## 5. HTTP/SSE 与前端兼容

/research、/research/stream、/healthz、topic/search_api、SSE type 和主要字段保留。同步入口继续使用 ResearchResponse 的原 JSON 结构；研究级故障仍为 HTTP 500，配置错误 400，原准入拒绝 429。流式响应头之后的研究故障继续通过原 error 帧表达。

同步 HTTP 与 SSE 都获得断连监听，后台执行方式一致；同步入口没有变成 SSE 或异步任务 ID 接口。

连接仍在且服务端 deadline 取消时，监督线程生成一致快照：

- SSE：现有 task_status 携带 cancelled/detail/error_code，最后 done + run_status=cancelled + warnings；保留已完成任务的真实终态，没有伪造 final_report。
- 同步 JSON：原结构中的 run_status=cancelled，保留任务快照和已有报告/笔记信息。
- 当前同步 provider 仍可能阻塞，容量继续保留；发出取消终态并不证明 provider 已退出。

前端修复了“done 已表示 cancelled，却因没有最终报告再次抛错”的路径。Abort 提示“连接已取消，后台可能仍在收尾”，不声明提供方停止计费。G3 的请求身份隔离、已完成任务保留、旧请求 catch/finally 防污染继续通过。

## 6. 失败复现、故障注入与实际结果

### 6.1 保留的失败证据

- [before.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/before.stderr.txt)：最初 9 个顶层测试、12 个失败（含 ASGI 2.4 四阶段 subTest），复现取消未传播、请求等待 provider、截止时没有及时终止、收尾引用未释放等路径。后续把四阶段 subTest 拆成独立用例，没有删去其断言。
- [frontend-first.stdout.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/frontend-first.stdout.json)：Abort 两项通过，实际后端 deadline 事件两项失败，原因是前端把缺少报告的 cancelled 改成 failed，已修复。
- [frontend-second.stdout.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/frontend-second.stdout.json)：研究状态已正确，但新增测试把告警错放在 progressLogs 中查找；前端原来使用 runWarnings 展示，修正测试观测位置，未声称告警原先丢失。
- [cancel-reason-race.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/cancel-reason-race.stderr.txt)：一次真实调度中 CLIENT_DISCONNECTED 被 generic CANCELLED 抢占；增加后台接受取消的顺序屏障，并补可控竞争测试。
- [done-close-before.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/done-close-before.stderr.txt)：正常读到 done 后关闭连接误把 completed 研究标 cancelled；新增终止结果识别和 Agent 正常关闭保护后通过。

没有跳过失败用例，也没有修改原测试证据来掩盖失败。

### 6.2 最终验收

| 检查 | 实际结果 |
|---|---|
| G4a.2 后端 | 27 tests，2.005 秒，OK，退出 0 |
| G4a.2 前端 | 4 checks，全通过，退出 0 |
| G0 | 15 tests，10.676 秒，OK，退出 0 |
| G1 | 14 tests，0.045 秒，OK，退出 0 |
| G2a | 23 tests，4.639 秒，OK，退出 0 |
| G2b | 29 tests，1.886 秒，OK，退出 0 |
| G3 后端 | 17 tests，0.379 秒，OK，退出 0 |
| G3 前端 | 17 checks，全通过，退出 0 |
| G4a.1 | 25 tests，0.919 秒，OK，退出 0 |
| vue-tsc --noEmit | 退出 0 |
| Vite 生产构建 | 14 modules，退出 0 |
| git diff --check / 暂存 | 通过，暂存为空 |

全部无跳过。错误日志为受控故障注入；既存 FastAPI 弃用提示未扩大处理。Vite 关于独立 outDir 不自动清空的提示符合隔离构建意图。

日志：[G4a.2](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g4a_2.stderr.txt)、[G0](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g0.stderr.txt)、[G1](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g1.stderr.txt)、[G2a](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g2a.stderr.txt)、[G2b](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g2b.stderr.txt)、[G3](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g3.stderr.txt)、[G4a.1](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g4a_1.stderr.txt)、[前端 G4a.2](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/frontend-g4a2.stdout.txt)、[前端 G3](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/frontend-g3.stdout.txt)、[类型检查](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/typecheck.json)、[构建](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/frontend-build.stdout.txt)。

27 项覆盖四阶段 disconnect/发送失败、2.4 无输出时的 disconnect、HTTP 同步取消/JSON、服务端 deadline、响应头失败、ASGI task.cancel、已完成与未开始任务、禁止新轮次/笔记提交、满交接队列、所属线程关闭、producer/监督线程启动失败、取消原因竞争、正常 done 后关闭及实际 SDK 流。

最后一轮 10 个主要断连场景，从测试观察到断连/发送失败条件至请求返回，测得约 0.4–5.3 毫秒，测试要求低于 0.2 秒：[latency-final.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/latency-final.json)。这是受控进程内 ASGI 测量，不是浏览器、反向代理或公网的时延保证；等待提交锁不包含在“取消已被接受”的承诺内。

G0 最终在 venv/g0-hf0ahanb 新环境构建 wheel/sdist、安装锁定依赖及 wheel、验证新增桥接模块和三种启动方式；没有依赖 backend/.venv 的额外手工包。证据：[g0-commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g0-commands.json)、[g0-setup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g0-setup.json)、[g0-installed-environment.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g0-installed-environment.json)、[g0-http-smoke.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g0-http-smoke.json)、g0-final-logs/。

前端产物在 venv/g4a2-front-2gp4gjtb/dist，未覆盖原 dist。Node 使用真实 api.ts 和编译后的 Vue setup；实际 ASGI deadline 样本经真实解析器进入前端，Abort 使用受控 fetch/ReadableStream。没有声称完成真实浏览器 DOM、TCP 或代理链端到端测试。

## 7. 文档修正、复跑及证据保护

G4a.1 报告只修改以下两行：

~~~bash
G4_PY="$G4_ROOT/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"
G4_FRONT="$G4_ROOT/code/chapter14/helloagents-deepresearch/frontend"
~~~

实际文件使用带花括号的 G4_ROOT 形式，避免变量名拼接；Bash 已实际解析并验证解释器可执行、前端 package.json 存在：[g4a1-command-fix.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g4a1-command-fix.json)。G4a.1 原证据目录指纹全部保持不变。

主要复跑命令，在指定 WSL 内执行：

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G42_ROOT="$PWD"
G42_PY="$G42_ROOT/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"
G42_FRONT="$G42_ROOT/code/chapter14/helloagents-deepresearch/frontend"
G42_NODE=/home/nhzj121/.nvm/versions/node/v24.15.0/bin/node

"$G42_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_4a_2*.py' -v
"$G42_NODE" "$G42_FRONT/tests/acceptance/phase4a2.mjs"
"$G42_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_1*.py' -v
"$G42_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2a*.py' -v
"$G42_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2b*.py' -v
"$G42_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_4a_1*.py' -v
"$G42_NODE" "$G42_FRONT/tests/acceptance/phase3.mjs"

G42_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
env -u G0_WORK_ROOT -u PYTHONPATH -u VIRTUAL_ENV G0_BASE_PYTHON="$G42_BASE" G0_UV=/home/nhzj121/.local/bin/uv "$G42_BASE" -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v
(
 cd "$G42_FRONT" &&
 test "$(git rev-parse --show-toplevel)" = "$G42_ROOT" &&
 "$G42_NODE" node_modules/vue-tsc/bin/vue-tsc.js --noEmit
)
~~~

G3 Python 验收的精确命令在 [g3.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/g3.json)。该历史测试会重写自身两份合成样本；本轮每次运行先保存字节，保存当前新样本到本阶段目录，再恢复旧样本，历史证据未改变。需要保护旧证据的复跑也应这样操作，不能无提示覆盖。当前样本：[fake-workflow.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/fake-workflow.json)、[fake-paused.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/fake-paused.json)。

各阶段精确 argv/cwd/退出码保存在同名 g*.json。构建命令与独立 outDir 见 [frontend-build.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a2_evidence/frontend-build.json)；不要清空或覆盖用户原构建目录。G4a.2 测试只更新本阶段临时样本/证据。

## 8. 剩余边界、回滚与 G5 前置条件

- 取消是协作信号。已执行的同步 HTTP、DNS、搜索、SDK 读取或文件系统提交可能继续；本阶段不杀线程、不关闭整个共享客户端，也不证明服务商已停止生成或计费。
- 断连请求可以先退出，但执行容量可能一直被 provider 占用。没有硬进程隔离或跨进程/跨机配额；每服务进程仍是 G4a.1 默认 2 个研究，多进程部署需计入 worker 数。
- 提交锁若长时间不释放，监督线程接受取消及生成终态会等待；ASGI 事件循环和断连请求不为这把锁阻塞。仍连接的客户端不能在“取消尚未被接受”时获得已完成取消的保证。
- 检测以 ASGI receive/send 提供的信息为准；代理缓冲、网络黑洞和服务端尚未观察到的断连仍依赖 deadline。没有本次验证之外的真实浏览器/反向代理/提供商 SLA。
- 终止结果之后只做正常传输收尾；没有增加传输总超时。慢客户端的发送背压可持续到 ASGI 报错/断开。桥接交接有界，但原任务事件队列和总体输入/输出预算仍属既有边界，未实施 G4b。
- 断连后的不可达事件不承诺送达。无持久化回放、重连恢复、分布式状态或额外取消 API。取消前已经提交的数据保留，真实笔记没有迁移或切换，安全 Repository 仍要求显式注入。
- G5 依赖漏洞治理尚未实施；本轮构建成功不替代发布依赖审计。真实部署的断连链路、应用停止接纳后的后台收尾和服务进程退出策略仍应在发布环境验收。

回滚可将本阶段桥接模块、main 接线、Agent 传输快照/关闭保护和前端配套作为一组回退到 2447fc9 的 G4a.1 行为，保留 G2 存储/版本安全和 G3 修复。先停止新研究并确认已有后台调用实际收尾；不能提前释放容量后并排启动另一套执行器。回退传输后须明确 HTTP 断连不再传播；不要用全仓库 reset/clean 清理用户文件，也不要回滚或覆盖笔记数据。

G4a.1 与 G4a.2 均已独立验收，完整历史回归通过，没有发现阻碍进入 G5 发布门的执行/传输层问题。G5 的依赖治理和正式部署验证尚未完成；本阶段停止，不自动实施 G4b、G5、G6，不提交或推送。
