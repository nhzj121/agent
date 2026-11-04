# G2b Agent 工具适配与笔记归属实施结果

日期：2026-11-03（Asia/Shanghai）。

**结论：真实 HelloAgents 0.2.9 扩展点门槛通过；最终 G2b 29 项、G0 15 项、G1 14 项、G2a 23 项均通过，无跳过。具备进入 G3 独立实施的前置条件。没有切换真实笔记工作区，没有实施 G3/G4a。**

## 1. 实施范围与环境

所有操作在 WSL 注册发行版 Ubuntu22.04.3 的 Linux 工具链内执行，每次先核对 Git 根目录为 /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source。基线 main / 755ae75958e6fb072c8a075bcbc55ad15d98bb17。

保留已有 G0/G1/G2a 修改、用户 README/Zone.Identifier、AGENTS.md、未跟踪 docs/tests。开始记录 179 个原有文件指纹；结束只有下表六个原有文件改变，其余保持，包括之前全部阶段报告、pyproject.toml、uv.lock、Tracker 和前端。未提交、暂存、推送或清理用户文件。

证据：[baseline.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/baseline.json)、[integrity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/integrity.json)。所有笔记实验均使用 TemporaryDirectory、合成数据、Fake LLM/Fake 搜索，无真实模型/搜索请求，无既有 notes/ 访问或迁移。运行库取 G0 已验收独立环境；G0 回归重新在另一全新环境构建安装。

## 2. 先验证框架扩展点

业务接线前先新增并运行 [test_phase_2b_tool_adapter.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_2b_tool_adapter.py)。它直接构造真实 ToolAwareSimpleAgent，注册实验用局部工具与 Fake LLM 视图，不继承 Agent，不替换 run/stream_run。

| 门槛 | 实测证据 |
|---|---|
| read 结果进入下一次模型输入 | 同步/流式均收到包含完整 v1 正文、版本和服务端 receipt 的工具结果 user 消息 |
| 生成开始时可冻结基线 | LLM invoke/stream_invoke 开始时冻结 v1，工具执行在模型输出耗尽后发生 |
| 同回答 read→update | 无前轮快照时 READ_REQUIRED；已有 v1、外部变 v2、同回答 read(v2)→update 时仍按 v1 冲突 |
| 同步/流式工具顺序 | 两者均 generation→read→generation→update→generation；监听器在每次工具执行后触发 |
| 并发 Agent 隔离 | 两个真实 Agent 并发处理不同笔记，只持有各自 receipt/冻结版本，互不串用 |

门槛 3 项顶层测试、多个同步/流式及前轮版本 subTest，全通过，退出 0：[extension-gate.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/extension-gate.json)、[extension-gate.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/extension-gate.stderr.txt)。随后才实施生产适配。原框架源文件位置与 SHA-256：[framework-manifest.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/framework-manifest.json)；未修改框架安装目录。

实验 Probe 仅证明扩展点可用，不是生产凭据授权器。生产实现采用下节完整消息和执行记录校验，比实验中的片段检查更严格。

## 3. 修改文件与职责

B 表示 code/chapter14/helloagents-deepresearch/backend。

| 文件 | 变更 |
|---|---|
| [services/note_versions.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/note_versions.py)（新增） | 不可变 ReadReceipt、GenerationBasis、GeneratedText、NoteScope；按 Agent/execution 分离的 VersionLedger |
| [tools/__init__.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/tools/__init__.py)、[project_note_tool.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/tools/project_note_tool.py)（新增） | note 兼容字符串入口、结构化 NoteToolResult/NoteWriteResult、版本授权与可信归属检查 |
| [services/agent_adapter.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/agent_adapter.py)（新增） | 组合式 ProjectToolAwareAgent + LocalLLMView；仅委托原版循环；监听结果安全投影 |
| [services/note_ownership.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/note_ownership.py)（新增） | 每 run 可信身份、任务 NoteBinding、最终报告幂等定位和生成基线持久化 |
| [agent.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py) | 增加显式 note_repository 注入；每次研究建立新 run；创建局部 Planner/Task/Reporter 工具视图；最终报告安全持久化分支 |
| [services/summarizer.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/summarizer.py) | 可选 task_agent_factory，按可信任务上下文创建局部工具；原过滤/清理和默认工厂保留 |
| [services/reporter.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/reporter.py) | 将原版响应的生成基线连同清理后的正文保留为 GeneratedText，返回值仍为 str |
| [services/notes.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/notes.py) | 明确 read 结果进入下一轮后更新；冲突须重新读取并重新生成 |
| [storage/file_notes.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/file_notes.py) | 增加锁内 create_once；修复并发目录扫描游标问题，保留原 G2a 文件/ETag/提交协议 |
| [G0 测试](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_0_environment.py) | 增加 tools 与三个 services 新模块的 wheel/sdist/独立导入断言，不删除原断言 |
| 三个 G2b 验收文件 | 框架门槛、版本授权、归属和工作流回归 |
| 本报告与 g2b_evidence/ | 命令、真实输出、失败复现、指纹和独立构建证据 |

没有复制/覆写 HelloAgents 核心循环。ProjectToolAwareAgent 是普通组合对象，Tool 仅继承框架工具接口；run/stream_run 恰好委托一次 upstream 对应入口。原 kwargs/max_tool_iterations、fallback、历史和输出片段仍由 upstream 处理，不额外请求模型。

## 4. 凭据结构、冻结和生命周期

- NoteScope：服务端确定 run_id、purpose、task_id，模型不能设置。
- ReadReceipt：receipt_id、execution_id、run_id、agent_scope、task/purpose、note_id、etag、完整快照 JSON 的 snapshot_digest、tool_execution_id。
- GenerationBasis：generation_id、execution/run/agent/task/purpose 和不可变 receipt tuple。
- GeneratedText：text、basis、artifact_id。只在正常生成完成时产生；Reporter 对正文过滤后以相同基线生成新的不可变文本对象。
- NoteBinding：任务关联/展示用 ID、路径、ETag，不授予更新权。
- NoteToolResult：NoteWriteResult 状态、兼容文本、可信 task_id；失败不返回成功 note_id。成功 read 的 persisted=False，写入成功 True，提交不确定 unknown。

生命周期：

1. 每个门面具有独立 ledger 和工具注册表；每次执行生成新的 execution_id。相同门面并发执行明确拒绝，避免上游共享 history 被竞争；不同 Agent 可以并发，LLM 对象本身不重构。
2. read 与 fresh create 返回完整快照并签发服务端 receipt，先存为待交付结果。幂等 create 命中只返回 ID 确认，不签发凭据；list/search/summary 和错误不授权。
3. LocalLLMView 在实际 invoke/stream_invoke 开始校验：上次模型消息前缀未变；本轮恰好追加 assistant 和 user 两条；user 内容必须精确等于本 execution 工具结果整批拼装的原框架消息。不是搜索任意文本中的 ETag/receipt_id，也不接受用户/历史里的相似内容。
4. 仅经过上述校验的完整快照成为当前冻结基线；输入被裁剪/改写时撤销旧授权。基线保持至下一次模型调用开始或执行结束，不在流正常耗尽时提前清空。
5. 本批次工具 read 只登记为待交付，不能修改已经生成的回答所使用的基线。因此同回答 read→update 无前轮基线则 READ_REQUIRED，有旧基线仍按旧 ETag。
6. update/delete 使用冻结 receipt.etag；Repository 读最新字节只比较 CAS。模型给 expected_etag/etag 时必须与可信基线一致，不能覆盖它。模型伪造 scope、receipt 或其他 run/task 参数明确失败。
7. 成功写入、CONFLICT、COMMIT_UNCERTAIN 撤销该笔记旧授权。同回答第二次 update 不获得第一次写入返回的新版本；必须重新 read 并让结果进入下一轮。没有自动刷新版本、自动合并或额外模型重试。
8. 正常、异常、流关闭都清空执行 ledger；需要传给持久化层的不可变 GeneratedText 基线独立保留。SDK 资源/强制网络取消不在本阶段保证范围。

真实框架拼装格式若将来改变，匹配将拒绝授予新写权，不能悄悄降级为扫描字符串授权。升级框架必须重跑门槛测试。

## 5. 归属、兼容性与显式启用

可信上下文由项目创建，run_id 每次研究随机生成：
- Planner purpose=planner，不从模型 title/tags/task_id 猜测任务归属。
- Summarizer purpose=task、task_id 来自调度中的 TodoItem。
- Reporter purpose=final_report，可以读取本 run 的任务/规划笔记；仅能修改本 final_report 身份的笔记。
- 外 run、未知/旧笔记归属不自动收编；task Agent 不能读取/更新别的任务。模型伪造归属返回 OWNERSHIP_ERROR。
- 只有验证成功的任务快照建立 NoteBinding；Reporter 仅凭 note_id 读取也能投影到真实 task_id。

保持工具名 note 及 create/read/update/delete/list/search/summary，成功文本保留独立 ID: 行。JSON 与原 key=value 参数仍由 upstream 解析。list/search 支持 limit、note_type，summary 从本 scope 可见文件派生；摘要不授予更新。字符串输出内容更结构化，未承诺逐字复制旧工具的所有排版。

行为收紧：无有效已交付 read 的更新失败；幂等重复 create 不覆盖；模型不能通过 tags/title 冒充任务；Planner 尚未有可信任务上下文时声明 task_id 的写入会失败。这些是安全边界，不增加推测式归属。

为避免旧 Tracker 从失败参数/文本推断假 ID，门面只投影可信 note_id/task_id。parser 失败也不会复用上次工具成功结果。Tracker 源码、事件类型与主要字段均不改变；结果状态的完整 UI 告警和投递协议仍属 G3。

**启用仅通过 DeepResearchAgent(config, note_repository=repo) 显式注入。** config.enable_notes 仍需为 True。Repository 必须由调用者在显式候选工作区构造。本次只在 TemporaryDirectory 中这样运行；不从 notes_workspace 自动构造 Repository、不迁移数据、不改变默认配置。

未注入时沿用原启动路径与旧 NoteTool；因此真实运行路径不会自动获得本阶段的新安全能力。旧工具的已知风险仍需通过后续经批准的工作区选择和接线启用来消除，不能把本报告当作真实目录已切换。

## 6. 最终报告幂等与安全持久化

最终报告身份由服务端 run_id + purpose=final_report + 固定 idempotency_key 决定，既不按 conclusion 类型也不按标题前缀查找；普通任务结论和其他 run 的报告不会被选择。

Repository.create_once 在同一独占文件锁内完成查找与创建，避免多实例 check-then-create 竞争。已有身份只返回原快照/ID，不修改正文；发现重复身份明确 CONFLICT。

Reporter 的 GeneratedText 随正文到最终持久化层。正文与 artifact 不一致拒绝；目标已有时，仅使用该 generation 的 receipt.etag，不拿 find 得到的当前 etag提权。没有对应快照则 READ_REQUIRED，过期则 CONFLICT。Reporter 工具先创建 draft、完整创建快照进入下一轮后，可以将后续正文安全更新到同一笔记，不再创建第二份最终报告。

同一已确认 artifact 再次 persist：仅在当前目标仍与确认版本相同才返回原确认；外部改动后冲突，不用旧内容覆盖。不同 owner 并发无基线创建最终报告的测试中只有一个成功创建，其他 READ_REQUIRED；文件始终一份。

若 Reporter 刚 update 后没有重新 read，却继续生成最终正文，持久化将拒绝缺基线的覆盖。这是按约束撤销授权的结果，不额外发模型请求补救。最终报告正文仍按既有 HTTP/SSE 输出，持久化失败记录结构化 last_note_result 与日志；G3 再完善用户可见告警。

## 7. 新发现的目录扫描问题

G2b 并发幂等测试首次失败：并行共享读中的目录枚举出现漏项/重复项，导致幂等查找错误。独立 [目录游标复现](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/directory-scan-before.stderr.txt) 也失败，证明不是 UUID 概率或未测试的共享 LLM 问题。

根因：os.listdir 在共用目录 fd 上使用共享 open-file-description 游标，多线程扫描会互相干扰。修复为每次相对目录 fd 重新 open(".") 取得独立扫描句柄，最后关闭；dup 仍共享游标，不能解决。没有改变锁/ETag/原子写入策略。新增八线程重复扫描断言修复后通过。

这是本阶段新补充的覆盖与修复；既有 G2a 报告及当时验收结论未编辑，原 G2a 23 项本次仍全部通过。

## 8. 实际测试结果与证据

| 套件 | 最终真实结果 |
|---|---|
| G2b（含 3 项前置门槛） | 29 tests，1.485 秒，OK，退出 0，无跳过 |
| G0 | 15 tests，11.473 秒，OK，退出 0，无跳过 |
| G1 | 14 tests，0.046 秒，OK，退出 0，无跳过 |
| G2a | 23 tests，4.840 秒，OK，退出 0，无跳过 |
| git diff --check / 暂存 | 通过，无暂存变更 |

G2b：[test_phase_2b_tool_adapter.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_2b_tool_adapter.py)、[test_phase_2b_versions.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_2b_versions.py)、[test_phase_2b_ownership.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_2b_ownership.py)。

覆盖正确读→生成→更新、外部改变导致过期冲突、模型伪造版本/receipt、同回答 read→update 和双 update、fresh/ID-only create、list/失败不授权、跨 Agent/task/run/execution、并发幂等、绑定不能升级冻结版本、parser 错误安全投影、COMMIT_UNCERTAIN 撤权、消息裁剪撤权、fallback/历史/异常/close、同步/流式工具顺序与显式完整工作流。

真实 opt-in 同步/流式工作流都禁用旧 NoteTool 构造，Fake 搜索 + Fake LLM 使用五次模型调用完成 Planner→Task create→总结→Reporter read/task+create/report→最终正文。每个 run 只有任务笔记和一份最终报告，没有额外请求来掩盖适配错误。

中间失败完整保留：
- [versions-first.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/versions-first.stderr.txt)：同步/流式子场景复用幂等任务，流式读到前一场景的新内容，导致 fixture 预期错误。测试显式重置合成初值，未删断言。
- [integration-first.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/integration-first.stderr.txt)：并发查找失败，随后独立复现目录游标问题并修复。
- [integration-second.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/integration-second.stderr.txt)：修复后最初 23 项通过，随后扩展安全与兼容边界至最终 29 项。
没有通过跳过或删除失败断言完成验收。错误路径测试中的 ERROR/WARNING 日志是预期故障注入输入，退出码仍由断言决定。

最终日志：[final.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/final.stderr.txt)、[g0.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g0.stderr.txt)、[g1.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g1.stderr.txt)、[g2a.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g2a.stderr.txt)。

G0 最终独立目录 venv/g0-a5gr2gls，重新构建 wheel/sdist、空 venv 安装带哈希依赖与 wheel、pip check、安装后新工具/服务导入、Fake HTTP、三种真实 Uvicorn 健康检查全部通过。未借用原 backend/.venv 手工包。精确命令/环境：[g0-commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g0-commands.json)、[g0-setup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g0-setup.json)、[g0-installed-environment.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g0-installed-environment.json)、[g0-http-smoke.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g0-http-smoke.json)。完整构建日志在 g2b_evidence/g0-logs/。既有许可证 table 弃用提示非失败，未扩大范围修改。

复跑命令（指定 WSL 仓库内，笔记数据全部临时生成）：

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G2B_PY="$PWD/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"
"$G2B_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2b*.py' -v
"$G2B_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_1*.py' -v
"$G2B_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2a*.py' -v

G0_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
env -u G0_WORK_ROOT -u PYTHONPATH -u VIRTUAL_ENV \
  G0_BASE_PYTHON="$G0_BASE" G0_UV=/home/nhzj121/.local/bin/uv \
  "$G0_BASE" -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v
~~~

精确 argv/退出码：[final.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/final.json)、[g0.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g0.json)、[g1.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g1.json)、[g2a.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2b_evidence/g2a.json)。

## 9. 剩余风险、回滚与进入 G3

- 版本绑定证明模型接收了可信完整快照，不保证它正确理解或语义合并正文。
- G2a 的普通编辑剩余竞争仍在；要求无覆盖应使用高安全维护窗口。未实际测试断电。
- G3 的事件 ID 并发、前端解析/取消、UI 告警尚未处理；本阶段只作必要的可信结果投影，未宣称解决投递可靠性。
- G4a 的有界 Worker、HTTP 断连、超时、SDK 流关闭/同步请求强制停止未实施。
- 原框架参数清理、流式 chunk 及 fallback 特征保留；未修复所有可能的框架 parser 边界。
- 单机进程间唯一创建依赖 G2a 同一 flock 协议；本阶段新增幂等竞争测试为多实例线程，既有 G2a spawn 进程锁/创建/CAS 仍通过，不声称做了多机测试。
- 真实工作区未启用新适配，不以旧目录作演练。真实模型质量与真实服务商网络行为未验收。

回滚：停止新执行，丢弃 execution ledger，保留 G2a 安全数据层与候选目录全部新数据；不以旧快照覆盖新数据。关闭显式 Repository 接线的安全回退应配合 ENABLE_NOTES=false，不回到旧 unsafe NoteTool 写入。保留用户原有修改和历史文档，不清理未跟踪文件。

扩展点、凭据、归属、幂等、兼容性与全部回归已通过，没有发现阻碍进入 G3 的本阶段遗留问题。下一阶段仍需单独授权；本阶段到此结束，不进行真实笔记切换、不提前实施 G3/G4a。
