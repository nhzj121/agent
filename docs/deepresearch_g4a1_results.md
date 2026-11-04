# DeepResearch G4a.1 实施结果

日期：2026-11-04（Asia/Shanghai）。

G4a.1 完成：新增 25 项离线验收全部通过；G0 15 项、G1 14 项、G2a 23 项、G2b 29 项、G3 后端 17 项和前端 17 项全部通过，无跳过。Vue 类型检查及生产构建通过。可以进入 G4a.2 的独立实施，但本阶段在此停止。

## 1. 基线与范围

所有项目命令在 WSL 注册发行版 Ubuntu22.04.3、Linux 仓库 /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source 中执行，先核对 Git 根目录。HEAD 仍为 main / 755ae75958e6fb072c8a075bcbc55ad15d98bb17；没有暂存、提交、推送、拉取或清理用户文件。

保留先前未提交的 G0–G3 代码、未跟踪审计资料及用户文件。本轮实施前保存 50 个相关源码、测试、阶段报告、依赖/锁文件的指纹，结束只有下表 6 个原有文件变化。依赖声明、锁文件、前端业务源码、G2 Repository/版本凭据/归属实现、历史阶段报告不变。证据：[baseline.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/baseline.json)、[integrity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/integrity.json)。

笔记测试均使用 TemporaryDirectory 和合成数据；Fake LLM/Search 或真实 OpenAI/HTTPX + MockTransport，不调用付费服务，不访问、迁移或修改真实笔记。G0 使用受控本地健康检查端口，其余运行测试阻断外部 socket/DNS。

G3 既有验收会重新生成两份临时 Repository 的合成 SSE 样本；首轮回归更新了 docs/g3_evidence/fake-workflow.json 和 fake-paused.json，其测试内容与通过结论不变。后续回归保存/恢复这些样本，另将本阶段新运行样本保存在 [fake-workflow.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/fake-workflow.json)、[fake-paused.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/fake-paused.json)。这些样本中的临时路径并非真实笔记工作区。

## 2. 修改文件与设计理由

B 表示 code/chapter14/helloagents-deepresearch/backend。

| 文件 | 变更及理由 |
|---|---|
| [B/src/config.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/config.py:19) | 6 个指定默认值和 MODEL_MAX_RETRIES；环境变量仍通过原 from_env 读取，正数/有限数校验 |
| [B/src/agent.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:186) | 每次 run 的 ExecutionControl；最多 3 个活跃任务的滑动调度；规划数量限制；协作检查点；取消状态；存活 Worker 引用保留运行锁和容量 |
| [B/src/main.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/main.py:29) | 每进程共用准入控制；在 Agent 构造和 HTTP/SSE 启动前拒绝超额请求；将同一上下文交给执行层；保持现有同步 StreamingResponse |
| [B/src/services/agent_adapter.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/agent_adapter.py:16) | LocalLLMView 在生成前检查控制信号；注册组合式 ControlledTool；关闭流式门面时清理本线程拥有的响应；原 ledger 冻结/清理顺序保留 |
| [B/src/services/summarizer.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/summarizer.py:37) | 总结入口检查；finally 除关闭上层迭代器和清 history 外，清理 SDK 响应登记，覆盖上游没有传播 close 的情况 |
| [tests/acceptance/test_phase_0_environment.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_0_environment.py:39) | 增强 wheel/sdist 和独立安装导入断言，包含新增包/模块；保留原验收断言 |
| [execution_control.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/execution_control.py:1)（新增） | 单调 deadline、Event、上下文绑定、提交边界锁、根/Worker 引用计数、独立响应登记、准入租约 |
| [project_llm.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/llm/project_llm.py:1)、llm/__init__.py（新增） | 组合适配现有 HelloAgents 配置和共享 SDK 客户端，显式预算/超时/重试及本次响应 close |
| [search_runtime.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/search_runtime.py:1)（新增） | 搜索调用前后协作检查，不改全局 SearchTool 或后端选择 |
| [controlled_tool.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/tools/controlled_tool.py:1)（新增） | 保留 Tool 名称/参数和展开行为；工具执行与接受取消使用同一控制锁，不改变笔记 ETag 授权 |
| [test_phase_4a_1_execution.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_4a_1_execution.py)（新增） | 16 项执行、准入、状态与提交次序验收 |
| [test_phase_4a_1_resources.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_4a_1_resources.py)（新增） | 9 项真实 SDK MockTransport、响应释放、预算、共享并发和搜索保护验收 |
| 本报告、docs/g4a1_evidence/（新增） | 命令、初始失败、最终输出、独立安装证据和范围指纹 |

没有复制/覆写 HelloAgents run/stream_run。Planner → Search → Summarizer → Reporter 保留；Queue、Tracker、HTTP 路径、现有 SSE type 和主要字段保留。G2a/G2b 的 Repository、ReadReceipt、GenerationBasis、版本授权和归属算法没有修改。

## 3. 调度与容量

### 3.1 配置

| 环境变量 / Configuration 字段 | 默认值 | 语义 |
|---|---|---|
| MAX_TASK_WORKERS / max_task_workers | 3 | 每研究最多同时执行 3 个任务 |
| MAX_ACTIVE_RESEARCH / max_active_research | 2 | 每服务进程接纳的研究数 |
| MAX_PLANNED_TASKS / max_planned_tasks | 8 | 规划产生的有效任务数上限 |
| RESEARCH_DEADLINE_SECONDS / research_deadline_seconds | 180 | 协作截止时间，使用 time.monotonic |
| MODEL_CONNECT_TIMEOUT / model_connect_timeout | 5 | SDK 连接及连接池等待的初始上限，单位秒 |
| MODEL_READ_TIMEOUT / model_read_timeout | 20 | SDK 读取及写入的初始上限，单位秒 |
| MODEL_MAX_RETRIES / model_max_retries | 1 | 最多额外重试 1 次；允许配置 0–4 次 |

这些是可调整默认值，不是服务商配额。MAX_ACTIVE_RESEARCH 在服务进程第一次准入时确定；改变它后重启该服务进程，不能通过每个请求创建新的 limiter 绕过已有活跃容量。多 Uvicorn 进程的总容量是进程数乘以每进程限制；不是全机最多 2 个研究。

### 3.2 Worker

流式执行保留完整任务列表。初始启动至多 max_task_workers 个线程；只有收到原内部完成标记、确认对应线程结束后，才补充下一任务。没有为 8 个任务一次性创建 8 条活跃线程，也没有无限待执行研究队列。同步 run 保留顺序执行，因此同样低于每研究上限。

Thread.start 失败时释放本次尚未运行的引用，将相应 TodoItem 标 failed / WORKER_START_FAILED，发送原 task_status 类型并继续调度其余任务；不等待不存在的完成事件。

规划超过 8 项时明确失败，保留实际规划列表和 PLAN_LIMIT_EXCEEDED 状态，搜索不启动。没有静默裁剪已规划任务。研究级规划/Reporter 异常仍为 failed；已完成任务不被伪造为任务失败。任务级搜索/总结异常保持 failed，Reporter 仍看到同样的对象状态。

### 3.3 研究准入和真实生命周期

[ResearchAdmission.acquire](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/execution_control.py:27) 是锁保护的非等待准入。两个 HTTP 路由共用进程 limiter；超额请求在 Agent 构造、Planner 和响应头之前返回 HTTP 429：

~~~json
{"detail":{"code":"RESEARCH_CAPACITY_EXCEEDED","detail":"active research limit reached"}}
~~~

ExecutionControl 保持一个执行入口引用和每个已经启动的 Worker 引用。正常结束、初始化失败和线程启动失败均回收对应引用；研究结束/迭代器关闭只释放入口引用。已阻塞的 Worker 必须结束同步调用并完成响应清理后才释放自己的引用。全部引用结束时才释放运行锁和准入租约，旧 Worker 未收尾时同一 Agent 也不能开启新 run。

事件消费在协作取消/deadline 后不 join 阻塞调用：将未终结任务标 cancelled、发送终态和 done，执行对象仍被 Worker 保持引用。后续新研究不能占用这些后台工作仍持有的容量。正常完成标记后的短 join 只用于确认已完成目标的线程退出。

直接嵌入调用 DeepResearchAgent.run/run_stream 时仍受每研究上限和控制上下文约束；进程级准入由 HTTP 服务边界管理。嵌入式多研究调用者应显式使用同一 ResearchAdmission，不能把独立 Python 调用当成 HTTP 服务配额已自动生效。

## 4. Deadline、状态与笔记边界

同一 ExecutionControl.id 作为 run_id，包含 Event、单调 deadline、取消原因与错误码。可在内部测试/程序调用时通过 run(..., execution=ctx) 或 run_stream(..., execution=ctx) 显式注入；默认自动创建。

检查点包括：研究开始、Planner 前后与规划数量验证、调度新任务前、搜索前后、总结入口和每个可见 chunk、LLM 每轮请求及重试、Reporter 前后、工具执行及最终报告持久化前。重试等待使用 Event.wait 和剩余预算，不超预算开始下一次尝试。

deadline 产生 DEADLINE_EXCEEDED，内部取消产生 CANCELLED；未终结任务成为 cancelled，已有 completed/skipped/failed 保留。run_status=cancelled，不启动 Reporter/新模型轮次/后续笔记写入，不产生伪造 final_report。同步返回 cancelled 和空/已有报告；SSE 使用现有 task_status 与 done，带取消码、detail 和 warnings。消费者提前关闭不会在 finally yield。

任务状态写入受同一控制锁和终态检查保护；搜索或模型的迟到返回在下一边界被拒绝，不能把 cancelled 改回 in_progress/completed。研究级致命异常会停止残余生产者开始后续阶段。

ControlledTool 与最终报告持久化在同一控制锁内检查后执行。已经开始、在接受取消之前提交的内容保留；接受取消之后拒绝新的提交。短文件操作可能跨过名义 deadline 完成，这是协作提交边界，不是文件系统事务的强制中断。锁不跨模型或搜索网络等待。

笔记版本凭据不受此锁替代：仍必须使用模型生成时冻结的 ETag，不能在提交前读取最新 ETag 授权。显式 Repository 注入方式未变，也未自动启用真实笔记目录。

流式上下文绑定只包围 next/close，不跨 yield 持有 ContextVar token；适配现有同步 StreamingResponse 可能在不同线程恢复迭代的行为。Worker 在线程内显式绑定自己的研究上下文。

## 5. SDK 超时、重试与释放

[ProjectLLM._request](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/llm/project_llm.py:14) 使用现有 HelloAgentsLLM._client 的 with_options 视图，共享底层连接池，SDK 内建 max_retries=0。项目层最多执行 1+MODEL_MAX_RETRIES 次创建请求；连接错误/超时、408/409/429/5xx 才可重试，其他状态直接失败。退避初始 0.1 秒、按倍数增长至最多 1 秒，受剩余预算约束，不额外叠加 SDK 默认重试。

每次尝试的 connect/pool timeout 为 min(5, remaining)，read/write timeout 为 min(20, remaining)。有效值传到真实 HTTPX request.extensions，验收直接检查。不能用调用时的 timeout 参数覆盖已冻结的研究预算。I/O timeout 是每类等待上限，不是严格请求总耗时保证。

stream_invoke 在 finally 显式关闭本次 SDK Stream；正常、迭代异常、提前 close 均覆盖。已经输出部分内容的流不重试，避免重复正文。响应登记由执行上下文按所属线程保存；Summarizer/ProjectToolAwareAgent 的关闭路径额外清理登记的响应，即使 HelloAgents 上游生成器保留内部 LLM 迭代器也不依赖垃圾回收释放连接。

不会通过关闭整个 OpenAI/HTTPX 客户端取消单个研究。并发共享客户端、另一条流和其他研究保持可用。未实现每研究客户端重建或共享 LLM/SearchTool 重构。

## 6. 失败复现与最终结果

先新增测试，再实施业务修改。原始日志保留：

- [before-all.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/before-all.stderr.txt)：13 项初始测试，4 个失败断言、10 个错误（含 subTest）。实测 8 个活跃 Worker、超量规划未拒绝；新控制接口缺失属于尚未实现的功能，不全部称为原缺陷。两处 Planner/Reporter 失败断言原先 patch 的服务被显式 Repository 初始化重建，随后修正测试接线，没有据此声称框架吞异常。
- [first.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/first.stderr.txt)：资源测试误把 SDK is_closed 方法当属性断言，修正为真实 is_closed()；没有修改 SDK 或放松断言。
- [g1-first.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g1-first.stderr.txt)：原私有 _execute_task 清理测试未建立研究上下文，新 helper 兼容无上下文的独立调用，保留全部历史断言后通过。
- [g0-first.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g0-first.stderr.txt)：干净安装 Fake HTTP 工厂替换触发 execution 参数误传。固定运行类型标识，保持旧 run(topic)/run_stream(topic) 测试工厂兼容；新增初始化失败/工厂兼容回收验收，再用新环境全量重跑 G0。

最终全部无跳过：

| 验收 | 数量 / 时间 | 结果 |
|---|---|---|
| G4a.1 | 25 tests / 0.921s | OK，退出 0 |
| G0 | 15 tests / 10.137s | OK，退出 0 |
| G1 | 14 tests / 0.041s | OK，退出 0 |
| G2a | 23 tests / 4.741s | OK，退出 0 |
| G2b | 29 tests / 1.864s | OK，退出 0 |
| G3 后端 | 17 tests / 0.526s | OK，退出 0 |
| G3 前端契约 | 17 checks | 全通过，退出 0 |
| vue-tsc --noEmit | — | 退出 0 |
| Vite build | 14 modules | 退出 0 |
| git diff --check / 暂存 | — | 通过；暂存为空 |

日志：[G4a.1](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g4a_1.stderr.txt)、[G0](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g0.stderr.txt)、[G1](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g1.stderr.txt)、[G2a](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g2a.stderr.txt)、[G2b](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g2b.stderr.txt)、[G3](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g3.stderr.txt)、[前端](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/frontend.stdout.txt)、[类型检查](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/typecheck.json)、[构建](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/frontend-build.stdout.txt)。

关键实测场景：

1. 8 项真实多线程搜索/总结活跃数不超过 3，同时确实存在并行；9 项规划不启动搜索。
2. 两个真实 HTTP 研究停在搜索屏障，第 3 个 SSE 请求 429，Agent 工厂仅调用两次；结束后 active=0。
3. 内部取消/假时钟截止后事件消费结束，而阻塞搜索、总结及真实 SDK MockTransport 流仍持有容量/运行锁；放行后才回收。迟到正文不将任务恢复 completed。
4. Planner、Search、Summarizer、Reporter 和线程启动的故障状态；同步/SSE deadline 状态相同；已过期/直接设置 Event 的上下文不启动模型。
5. 接受取消与已进入工具提交边界的先后关系可控；取消后拒绝笔记写入。
6. SDK 正常/异常/提前关闭、强引用保留上游 LLM 迭代器时的清理；关闭一条流不关闭共享客户端/另一条流；16 次共享 SDK 并发输入输出一一对应。
7. 429 有界重试、剩余预算缩小时真实 HTTPX timeout 同步缩小、不重放部分输出；原 SearchTool 显式覆盖和 advanced 回退保护继续通过。

G0 在 venv/g0-n_sj55n4 新建独立构建/安装环境，包含新增模块，三种原 Uvicorn 启动形式的健康检查全部通过；未依赖原 backend/.venv 手工包。证据：[g0-commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g0-commands.json)、[g0-setup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g0-setup.json)、[g0-installed-environment.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g0-installed-environment.json)、[g0-http-smoke.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/g0-http-smoke.json)、g0-logs/。

前端构建输出到 venv/g4a1-front-5b3k3zqf/dist，不覆盖原 dist，也不清空已有目录。Vite 提示输出目录不在前端根内、不自动清空是预期行为；既存弃用提示未借机扩大改造。测试中的 ERROR/WARNING 日志为受控失败注入，不是跳过的失败。

## 7. 复跑命令

每条命令均先定位和验证指定 WSL 仓库。以下在该 WSL 中执行：

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G4_ROOT="$PWD"
G4_PY="${G4_ROOT}/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"

"$G4_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_4a_1*.py' -v
"$G4_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_1*.py' -v
"$G4_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2a*.py' -v
"$G4_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2b*.py' -v
"$G4_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_3*.py' -v

G4_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
env -u G0_WORK_ROOT -u PYTHONPATH -u VIRTUAL_ENV  G0_BASE_PYTHON="$G4_BASE" G0_UV=/home/nhzj121/.local/bin/uv  "$G4_BASE" -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v

G4_NODE=/home/nhzj121/.nvm/versions/node/v24.15.0/bin/node
G4_FRONT="${G4_ROOT}/code/chapter14/helloagents-deepresearch/frontend"
"$G4_NODE" "$G4_FRONT/tests/acceptance/phase3.mjs"
(
 cd "$G4_FRONT" &&
 test "$(git rev-parse --show-toplevel)" = "$G4_ROOT" &&
 "$G4_NODE" node_modules/vue-tsc/bin/vue-tsc.js --noEmit
)
~~~

G3 Python 测试会重写它原有两份合成事件样本，需保留旧证据时先复制样本再运行。生产构建应使用新的独立输出目录；本次精确 argv/cwd/输出目录见 [frontend-build.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/frontend-build.json)。各阶段精确执行命令分别保存在相应 g*.json，前端见 [frontend.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g4a1_evidence/frontend.json)。

## 8. 兼容、可靠性边界及回滚

原有源目录启动、--app-dir src 和 wheel 安装后的 main:app 启动均通过 G0 回归。HTTP 路径、请求 topic/search_api、SSE type 保留；新增 429 拒绝，超量规划明确失败，deadline/内部取消通过原 cancelled/run_status/warnings 表达。原无上限执行不再被保留为默认行为。

仍然存在的边界：

- **没有 G4a.2 异步 SSE 桥接或 HTTP disconnect 传播。** 浏览器 Abort 仍只是停止接收，不能据此确认后台收到取消；只有执行层显式 Event/deadline/研究迭代器实际 close 已接线。既存同步响应在 ASGI 断开时何时关闭、从未开始消费的响应如何释放，仍须 G4a.2 独立验证。
- Event/deadline 不能强制终止正在等待的同步 HTTP、DNS、第三方搜索或 SDK 读取。Planner/Reporter 等当前同步调用未返回时，当前入口也可能等待超过名义 deadline；返回后检查阻止后续阶段。受控阻塞流也在提供方放行后才由所属线程关闭。
- 超时是连接/读写等待上限；服务端持续发送数据可能令总请求耗时更长。没有硬线程/进程终止、计费立即停止、严格 180 秒返回的承诺。
- 全局 SearchTool 和其后端超时/内部 futures 保留；搜索可能长时间占住容量。没有为此重构共享对象。准入和 Worker 数有限，不等于每种第三方库内部线程数都被本项目限制。
- 事件消费取消后，不保证尚在收尾的事件送达客户端；进程内 Tracker 仍不是持久事件总线。取消前提交保留，不能通过回滚删除它们。
- NoteTool 安全路径仍需显式 Repository 注入；未迁移真实笔记。普通编辑竞争、模型质量、输入预算/G4b、G5 漏洞治理等边界不变。未验证真实服务商长时网络行为或费用。
- HTTP 进程准入是进程内上限，多进程/多机更高层配额未实现。共享底层客户端保持打开供其他 Agent 使用；本次保证请求响应释放，不声明强行关闭共享连接池。

回滚应整体回退本阶段执行层、控制门面及 HTTP 准入接线，保留 G2a/G2b 数据/授权和 G3 事件修复。因为当前 HEAD 不包含此前未提交阶段成果，不能使用 git reset/clean 当作阶段回滚。先停止接纳新研究，确认旧 Worker 和已有 SDK 调用真实收尾再重启/替换执行器，不能释放旧容量后并排再开新执行器掩盖后台工作。无需数据迁移或笔记回滚，也不能通过旧笔记快照覆盖新提交。

G4a.1 验收、完整历史回归和构建通过，未发现阻碍 G4a.2 的执行层问题。G4a.2 仍需按独立任务实现和验收；本阶段不自动进入后续阶段。
