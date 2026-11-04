# G1 核心缺陷修复结果

日期：2026-11-03（Asia/Shanghai）。

**结论：G1 14 项通过，G0 回归 15 项通过，均无跳过。具备进入 G2a 独立 Repository 开发/验收的前置条件；不授权真实笔记并发写入。G1 到此停止。**

## 1. 基线与改动范围

在 WSL 注册发行版 Ubuntu22.04.3 内核对 Linux 当前目录与 Git 根目录，均为 /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source。Git 基线 main / 755ae75958e6fb072c8a075bcbc55ad15d98bb17。

开始前 pyproject.toml / uv.lock 已有 G0 修改，AGENTS.md、根 README.md、Zone.Identifier、docs/、tests/ 等存在未跟踪文件。均保留，不还原、不清理、不暂存、不提交或推送。本阶段依赖配置 SHA-256 保持不变，未访问既有笔记、未请求真实模型/搜索 API。

证据：[baseline.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/baseline.json)、[integrity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/integrity.json)。相对 G1 开始，只改变以下六个业务源码与一个 G0 验收脚本，其他记录文件保持一致；新增 G1 测试、报告和证据。

## 2. 根因、修改文件与行为差异

B 表示后端 src 目录。

| 项目 | 文件/函数 | 根因与修复路径 |
|---|---|---|
| A01 | [agent.py:125](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:125) run | _execute_task 是生成器，仅调用不会执行搜索/总结。改为耗尽生成器；同步 run→规划/必要时 fallback→逐任务 search+summary→Reporter。单任务、三任务和 fallback 都实际执行并返回完成状态/总结。 |
| A02 | [agent.py:222](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:222) run_stream.worker | 原来只发 failed 事件，对象仍 in_progress。捕获异常时先设置 task.status=failed，再发送原事件；Worker 完成后 Reporter 从同一对象构造 prompt，三者一致。不新增事件、重试或线程模型。 |
| A03 / A19 | [utils.py:19](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/utils.py:19) ThinkingFilter；[utils.py:50](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/utils.py:50) strip_thinking_tokens；[summarizer.py:63](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/summarizer.py:63) generator | 原流式解析提前输出半个开始标签；原同步切片在反向标签下无法前进。共用增量状态机，记录嵌套深度，暂存可能的标签前缀；每轮消费字符/标签或等待下一块。同步一次 feed、流式逐块 feed，规则一致。 |
| A04 | [summarizer.py:63](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/summarizer.py:63) generator；[agent.py:291](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:291) _execute_task | 原 finally flush 再 yield，导致 ignored GeneratorExit，并跳过 clear_history。finally 不再输出；正常/异常/close 都关闭本层拥有的内层迭代器并清理历史。执行器也显式关闭 summary_stream，仅正常完成后读取 summary_getter 并标记 completed。流式 Summarizer 的普通 cleanup 异常不遮盖已有生成异常；记录警告，正常路径 cleanup 失败则传播。 |
| A11 | [text_processing.py:6](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/text_processing.py:6) strip_tool_calls | 正则在 JSON 数组第一个右方括号终止，参数残留。改为扫描标记，跟踪数组括号、JSON 双引号与转义，多标记逐个清除，标记外正文/普通方括号保留。同步 Summary、Reporter、stream getter 沿用现有清理位置；不重写框架工具语法。 |
| R05 | [planner.py:31](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/planner.py:31) plan_todo_list；[reporter.py:22](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/reporter.py:22) generate_report | 原 run 返回后才 clear。改为 try/finally，成功/异常均调用 clear_history，异常仍传播。不声称此前普通首轮失败必然泄漏跨请求历史。 |

测试变更：

- [test_phase_1_core.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_1_core.py)：新增复现与回归。
- [test_phase_0_environment.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_0_environment.py)：仅调整运行保护指纹的基准。原脚本以 G0 实施前源码哈希作为永久门槛，会拒绝后续授权修改。现在在 RunContext 开始时对历史 manifest 定义的原有路径建立当前指纹，结束逐一断言不变，且不再豁免配置文件。保留所有笔记、空环境、构建断言；历史 baseline.json 未修改。没有删除失败断言或跳过测试。

## 3. 文本与资源边界

开启 strip_thinking_tokens 时：

- 精确小写开始/结束标签支持任意 chunk 边界，嵌套按深度匹配。
- 孤立结束标签丢弃；未闭合开始标签之后的内容丢弃。
- EOF/close 时残缺标签前缀（如 <thi）不输出。普通比较表达式与无关尖括号保留。
- 关闭过滤开关时思考文本原样输出；最终工具标记清理保持。
- 工具标记内数组、字符串、转义均处理；遇未闭合工具标记，保守丢弃剩余后缀，不承诺挽回混杂正文。
- 缓存前缀可能改变分片粒度，正文顺序保持，不承诺逐个 SSE chunk 与旧版相同。
- finally 不 yield。仅关闭项目拥有的 Python 迭代器；未改 HelloAgents，也不声称强制停止同步 HTTP 或保证 SDK 内部资源释放（T23 留待 G4a.1）。

## 4. 修复前后实际测试

业务源码修改前先编写并运行测试：
Ran 11 tests in 3.048s，FAILED (failures=115, errors=2)，退出 1。115 包含分片组合 subTest，并非 115 个顶层测试。一个错误为畸形标签独立子进程超过 3 秒，另一个为 cleanup 异常遮盖原异常。没有跳过或删除这些断言。

证据：[before.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/before.json)、[before.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/before.stderr.txt)。

随后补充执行器关闭、同步总结清理及审计 T11 单 chunk 中途关闭测试。精确 A04 另在临时目录加载 git show HEAD 的原 Summarizer 模块验证：第一次 next 返回 prefix，close 报 ignored GeneratorExit、历史未清理；第二次 close 收尾。没有恢复工作树源码。证据：[a04-before.stdout.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/a04-before.stdout.txt)。不把这部分补测冒充为初始 11 项的覆盖。

| 验收 | 真实结果 |
|---|---|
| 最终 G1 | 14 tests，0.057 秒，OK，退出 0，无跳过 |
| G0 回归 | 15 tests，26.356 秒，OK，退出 0，无跳过 |
| git diff --check | 退出 0 |
| G0 依赖配置 | 相对本阶段开始指纹不变 |

G1 覆盖单/多任务/fallback；搜索和总结异常；所有单分割点与逐字符 chunk；嵌套/反向/未闭合标签；3 秒畸形输入子进程；正常/异常/部分关闭；cleanup 失败保留原异常；嵌套工具 JSON、多标记、转义；Planner/Reporter 正常/异常历史清理；正常 SSE 顺序与字段。

模型响应/流使用 FakeAgent，搜索使用 Fake dispatch/context。外网 socket/DNS、真实 LLM 初始化与 NoteTool 构造设失败 guard；笔记关闭并指向 TemporaryDirectory。Worker 失败与 cleanup 注入故障产生的 ERROR/WARNING 是预期测试输入，不是忽略的失败。

日志：[after.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/after.stderr.txt)、[g0.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/g0.stderr.txt)。G0 实际构建安装命令、环境、HTTP 结果：[g0-commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/g0-commands.json)、[g0-setup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/g0-setup.json)、[g0-http-smoke.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g1_evidence/g0-http-smoke.json)。

## 5. 复跑命令

在 WSL Ubuntu22.04.3 内执行。G1 使用 G0 验收的独立运行环境，测试将当前 src 放入导入路径首位，因此验证当前源码，不误测旧 wheel。

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G1_PY="$PWD/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"
"$G1_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_1*.py' -v

G0_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
env -u G0_WORK_ROOT -u PYTHONPATH -u VIRTUAL_ENV \
  G0_BASE_PYTHON="$G0_BASE" G0_UV=/home/nhzj121/.local/bin/uv \
  "$G0_BASE" -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v
~~~

G0 本次创建 venv/g0-6zbs9je7/runtime，实际重新运行隔离 wheel/sdist 构建、空 venv 创建、带哈希锁依赖安装、wheel 安装、pip check、安装导入、Fake 路由及三种 Uvicorn 健康检查，不使用原 backend/.venv 手工包。构建仍有既存 license table 弃用提示，非失败，未扩展范围改依赖或许可证。

## 6. HTTP / SSE 兼容性

main.py、models.py、配置、前端、Search、NoteTool、Tracker 均未改。Planner → Search → Summarizer → Reporter 顺序保留。

同步仍返回 SummaryStateOutput，现在确实执行任务；真实部署时将产生预期搜索/模型耗时与费用。同步异常仍向上传播，不新增容错或重试协议。

正常单任务事件顺序：
status → todo_list → task_status(in_progress) → sources → task_summary_chunk → task_status(completed) → final_report → done。
task_id、step、stream_token、content 及 final_report 主要字段保留。失败仍发 task_status(failed)，修正对象状态进入 Reporter。多个 Worker 的交错顺序仍无保证。

G0 Fake healthz、/research、/research/stream、error 帧及真实本机启动健康检查均通过；不代表真实研究质量验收。

## 7. 限制、回滚与 G2a 前置条件

- G2 NoteTool 并发/路径/ETag/归属未实施。真实笔记工作区不得用于验证。
- G3 Tracker、前端 SSE 解析未处理。工具标记修复覆盖现有最终文本清理位置，未增加流式工具标记缓存协议或改写上游工具 parser。
- G4a 有界 Worker、超时、HTTP 断连取消与 SDK 关闭问题保留；run_stream 关闭仍可能等待 Worker。
- 未重构共享 LLM/SearchTool/Queue，未新增 Agent 能力或升级依赖。
- 清理保证本层调用尝试，不保证上游 clear_history 自身失败时历史已清空。Planner/Reporter 的标准 finally 清理失败也会传播。
- Fake 覆盖不等于真实模型效果评估。

回滚只回退本阶段列出的六个源码及测试变更，不恢复整个工作树、不清理用户未跟踪文档。保留 G0 依赖与环境，无笔记格式变更/数据迁移。回退后仍应 ENABLE_NOTES=false，避免回到不安全笔记写入。

G1 指定问题修复、G0 回归通过，没有发现阻碍 G2a 独立 Repository 工作的问题。下一步等待用户指令；G2a 仍只用临时目录/副本，G2b 才接 Agent，不授权真实数据写入。
