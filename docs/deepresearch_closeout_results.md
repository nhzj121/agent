# DeepResearch G0–G5 工程收尾与真实运行验收准备

日期：2026-11-04（Asia/Shanghai）。结论：启动文档已与当前实现对齐，Fake/Mock 工程验收通过；可开始人工真实服务验收，尚未证明真实模型质量、宿主浏览器/代理链或服务商停止计费行为。未实施 G4b/G6。

## 1. 修改与运行方式

仅修改根 [README](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/README.md) 和 [后端 README](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/README.md)，新增本报告及 closeout_evidence/。已阅读 G0、G1、G2a、G2b、G3、G4a.1、G4a.2、storage activation、G5 报告，并以当前 config/main/工厂、存储 CLI、模型适配、搜索及前端入口为准；没有把历史报告中的“尚未实施”当作当前事实。

- 统一 WSL2/Linux、CPython **3.12.14**、uv **0.12.7**、Node **24.15.0** / npm **11.12.1**。
- 后端使用独立新环境、现有 uv.lock、显式解释器启动 main:app，监听 127.0.0.1:8000。前端实际 **5174**，使用 --strictPort 避免端口漂移。
- ENABLE_NOTES=false：不打开任何笔记工作区，研究仍可执行，任务/报告 note_status=disabled。
- ENABLE_NOTES=true：必须 files_v2、已激活的新 NOTES_V2_WORKSPACE、真实绝对保护源 NOTES_WORKSPACE 和额外保护清单；缺失/非法即拒绝，无旧 NoteTool 回退。首次 init 与已有目录重启分开说明。
- 补全空新目录初始化、check、模型/搜索变量、无 .env 自动加载、手工编辑窗口、前台启动/停止及无笔记安全回滚。不覆盖笔记、不复制激活标记重绑定，不改已有数据。
- 明确 **G5 后原 node_modules/dist 未被替换，需按新锁 npm ci --ignore-scripts**。本轮同样只安装到独立副本，未重装用户原环境。

目前可运行的工程能力：同步 JSON/SSE 研究工作流、任务/笔记状态分离、临时安全笔记真实落盘及报告幂等、错误配置拒绝、协作取消/断连传播与后台容量保留。上述研究能力本轮由 Fake/Mock 证明，真实服务兼容性仍须下一节验收。

## 2. 本轮实际复验

工作区 main / 2447fc91d41b3a46a7a4896d216355fad84abbfa；WSL Ubuntu22.04.3。独立产物保留于根 venv/closeout-pfkcu4so/；临时笔记由 TemporaryDirectory 清理，未接触真实旧工作区。

| 检查 | 实际结果 |
|---|---|
| 文档安装命令 | 独立源码副本 uv sync --locked --no-dev --python <3.12.14基础解释器>；安装 55 包，pip check 通过，锁未改变 |
| G0 | 15 tests / 12.503 秒，wheel/sdist、新环境安装、三种 Uvicorn 启动及 Fake HTTP 通过 |
| G3 后端 | 17 tests / 0.416 秒，通过 |
| G4a.2 | 27 tests / 1.736 秒，ASGI 断连、发送失败、deadline、容量和终态通过 |
| storage activation | 22 tests / 11.709 秒，真实 Uvicorn 默认工厂、临时任务/报告落盘、重启与两种模式通过 |
| 文档 CLI | 6 个场景通过：init、files_v2 check、manual-begin/end、disabled check、缺少 mode 退出 2 |
| 前端干净安装 | npm ci --ignore-scripts，51 packages；安装自带审计返回 0 vulnerabilities；不是重新开展 G5 全量审计 |
| 类型检查 / 生产构建 | 退出 0；Vue/TS 类型检查、Vite 6.4.5、14 modules |
| 前端 G3 / G4a.2 | 本轮后端新样本经真实 api.ts/编译 Vue setup，17 + 4 checks 全通过 |
| Vite 真实启动 | 127.0.0.1:5174 的 / 与 /src/App.vue 均 200；仅向本轮进程组发 SIGINT，进程已退出 |
| 文档/范围检查 | Bash 语法、内部文档链接及 Git diff 检查；具体结果见 final-validation.json |

**后端共 81 tests、前端 21 checks，均无跳过；六个 CLI 场景单列。** G1/G2/G4a.1 的独立完整套件没有重复运行，本次只选与启动、状态、存储接线、取消和前端直接相关的验收；G5 的完整历史结果仍保留。没有把预计失败的缺少 mode 拒绝或测试停止时的 SIGINT 当作失败遗漏。

主要命令及日志：

~~~text
UV_PROJECT_ENVIRONMENT=<新环境> uv sync --locked --no-dev --python <3.12.14基础解释器>
uv pip check --python <新环境>/bin/python
<基础解释器> -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v
<本轮新runtime>/bin/python -B -m unittest discover -s tests/acceptance -p 'test_phase_3*.py' -v
<本轮新runtime>/bin/python -B -m unittest discover -s tests/acceptance -p 'test_phase_4a_2*.py' -v
<本轮新runtime>/bin/python -B -m unittest discover -s tests/acceptance -p 'test_storage_activation*.py' -v
npm ci --ignore-scripts
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit
npm run build
node tests/acceptance/phase3.mjs
node tests/acceptance/phase4a2.mjs
npm run dev -- --host 127.0.0.1 --port 5174 --strictPort
~~~

这些是已执行命令摘要，不要将其路径占位符原样执行。完整 argv/cwd/退出码见 [命令与日志目录](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/closeout_evidence)、[后端汇总](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/closeout_evidence/regression-results.json)、[安装命令](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/closeout_evidence/documented-sync-command.json)、[CLI](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/closeout_evidence/documented-cli-checks.json)、[实际研究落盘样本](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/closeout_evidence/regenerated/storage_activation_evidence/actual-startup-workflow.json)、[前端启动](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/closeout_evidence/frontend-startup.json)。

复跑后端可用本轮 [控制脚本](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/closeout_evidence/run_startup_checks.py)，参数与 G5 控制脚本相同：--work-root 指向根 venv/ 下一个新的空环境目录，--output 指向独立日志目录，再指定 --base-python 和 --uv 的实际路径。脚本会保存/恢复旧合成证据。不要直接覆盖阶段证据复跑；[history-preservation.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/closeout_evidence/history-preservation.json) 记录本轮恢复结果。

## 3. 后续人工验收清单与通过标准

以下由操作者在明确服务额度后手工执行，本轮没有执行真实研究。使用**另一个专门用于真实验收的新目录**，不选择历史 notes，不放真实 key 到报告。每项记录日期、版本、脱敏提供商/模型、run_id、终态、告警和是否通过；不能只记录“页面有报告”。

| 步骤 | 操作 | 通过标准 |
|---|---|---|
| 1. 准备 | 按后端手册选择独立解释器；先 ENABLE_NOTES=false；配置真实模型 URL/ID/key 和明确搜索后端；人为设定可接受的服务额度 | check=disabled、/healthz=200；保留版本/配置但不保存密钥。健康检查不代替模型测试 |
| 2. 真实同步研究 | 对同一个简短、可查证主题手工 POST /research，topic 与可选 search_api 不变 | 正常成功案例有完整总结/报告；检查 run_status、每任务 status、来源链接；无笔记状态全部 disabled。partial/failed 必须保留原因，不能当“全成功” |
| 3. 真实 SSE | 手工 POST /research/stream（curl --no-buffer，示例在根 README） | 可观察规划→任务→报告，run_id 一致；收到 done 并核对 run_status，或真实 error；无终止帧 EOF 必须报协议异常。不能把 HTTP 200/done 单独当成功 |
| 4. 浏览器 | 按新锁 npm ci/build；启动 5174，在宿主实际浏览器打开 localhost:5174，检查网络/控制台并完成一次研究 | 请求确实到 8000，分片及时展示；任务/来源/工具/报告一致，控制台无未处理异常；任务失败与笔记失败显示分离。保留人工观察，不能以本轮 WSL HTTP smoke 替代宿主网络/DOM |
| 5. 安全笔记 | 新空目录 init/check 后启用 files_v2，重新启动，再执行短研究；只检查该新目录 | 正常成功案例任务及 final_report note_status=saved，文件内容与输出一致；run_id/purpose/task_id 归属正确，每 run 只有一个 final_report；重启新研究不串用旧 run。若模型未遵循读→生成→更新导致冲突，记录实际告警，不准改用最新 ETag 强行放行 |
| 6. 失败与编辑 | 仅在验收目录开启 manual-begin，运行一次短研究，再完成保存并 manual-end | 笔记 paused/error 清楚可见、无虚假 ID；成功总结不被误标为研究失败；end 校验后恢复。手工非原子保存/不参加锁的竞争不能作为安全保证 |
| 7. 浏览器取消/抢占 | 分别尝试规划、搜索、总结、Reporter 阶段停止；取消后立即开始新研究，并检查旧请求迟到结果 | 页面及时结束旧接收，已完成任务保留；新请求不被旧事件/catch/finally 污染。客户端断开不要求收到 cancelled 帧。记录实际停止时延；未收尾请求仍可能占用容量，429 可以是正确结果 |
| 8. deadline/代理/收尾 | 新启动测试进程可调小 RESEARCH_DEADLINE_SECONDS；连接保持时验证 cancelled。再经实际部署代理重复 SSE/取消。停止新提交，等 provider/搜索确实返回再 Ctrl+C | deadline 不启动后续阶段，已完成终态不倒退；慢/缓冲代理不造成假完成。取消前提交保留，取消接受后无新提交；provider 结束后容量可恢复。记录可观察的日志/服务商请求结束证据，无法观察的条目标“待验证”，不得编造后台已 idle |

执行取消测试时，若某阶段过快未命中，记录“未命中该阶段”并用可观察的请求重新验证，不在业务代码里临时插入 sleep。模型/搜索已发出的同步调用可能继续，服务商用量需单独核对；计费不立即停止不能自动判作项目取消传播失败，也不能对外宣称“费用已停止”。

## 4. 目前边界与 G4b/G6 前事项

- 文档偏差已修正；业务源码、G2/G3/G4 安全协议、依赖与锁、正式 .env/凭据、忽略规则及历史报告不变。原有用户修改/未跟踪资料保留，不提交或推送。
- 仍无公开 idle/drain API 或保证 daemon 后台线程排空的停服协议。/healthz、done、Abort 和服务进程退出不证明远端工作停止；不确定时保留目录原位，避免并排替代执行器。该边界仅如实说明，没有新增管理接口。
- 单机多进程锁已在历史验收验证；本轮服务默认单进程，准入仍是每进程 2 个研究。实际多进程/长时间压力和全机器配额未验证。
- G4b 前先完成上表的实际提供商/浏览器基线，记录长输入、慢搜索/客户端、容量恢复与总体预算需求；G4b 的上下文/事件预算和长时压测未实现，不承诺无限长研究稳定。
- G6 前固定真实成功/失败案例与质量评估标准，区分模型工具遵循问题、来源质量问题和工程缺陷，再决定新增 Agent 能力；不能用架构扩张代替未通过的真实基线。
- npm 零已知漏洞沿用 G5 快照，本轮 npm ci 自带审计亦成功，但不等于后端 CVE、认证/公网部署或供应链风险已全面审查。正式发布前重核审计和目标部署链。

本轮工程收尾完成并停止，等待下一步指令。
