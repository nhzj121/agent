# DeepResearch 安全 Repository 正式接线与启动验收结果

日期：2026-11-04（Asia/Shanghai）。

**服务配置接线完成。新增 22 项验收通过，真实 Uvicorn main:app 使用默认服务工厂完成 files_v2 的 HTTP/SSE 研究、落盘及重启验证；G0–G4a.2 全部历史验收、Vue 类型检查和生产构建通过，无跳过。没有配置或激活任何真实运行目录，没有迁移旧笔记，没有实施 G5 或提交/推送。**

## 1. 已确认的配置决策

用户本轮确认：

1. ENABLE_NOTES=true 时，没有显式 NOTES_STORAGE=files_v2 就拒绝启用；安全降级必须明确设置 ENABLE_NOTES=false。
2. 管理员只对显式指定的空新目录执行验证/初始化，生成激活标记；服务只接纳带合法标记的目标。
3. 原 NOTES_WORKSPACE 和项目 backend/notes 是保护源，新目标不能与其相同、互为父子或通过符号链接别名混用。

为避免把原写入路径误当作新目标，新增 NOTES_V2_WORKSPACE；原 NOTES_WORKSPACE 在新服务配置中只表示旧源保护路径，不再用于创建旧 NoteTool。

| 配置字段 / 环境变量 | files_v2 启用时的要求 |
|---|---|
| enable_notes / ENABLE_NOTES | true；无笔记模式显式 false |
| notes_storage / NOTES_STORAGE | 必须精确为 files_v2；缺失、空值、legacy/未知模式均拒绝 |
| notes_v2_workspace / NOTES_V2_WORKSPACE | 已存在、已激活的新目录，绝对 Linux 路径 |
| notes_workspace / NOTES_WORKSPACE | 原旧源的真实绝对路径，作为保护项；默认 ./notes 不满足显式保护要求 |
| notes_protected_workspaces / NOTES_PROTECTED_WORKSPACES | 补充保护源列表；环境变量使用 JSON 数组，默认 [] |

配置是服务环境/管理员操作，不新增 HTTP 路径字段或模型参数。主程序仍不自动加载 .env，必须由启动器实际导出变量。不同真实旧源应由管理员明确补充，不能根据测试路径推断。

## 2. 激活与启动方式

以下是部署示例，本轮仅对 TemporaryDirectory 中的合成目录执行了对应操作。首先人工选择并创建一个独立空目录；服务和初始化命令都不会自动 mkdir。

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend
test "$(git rev-parse --show-toplevel)" = "/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source" || exit 1
NOTES_PY=/absolute/path/to/linux/environment/bin/python

export ENABLE_NOTES=true
export NOTES_STORAGE=files_v2
export NOTES_V2_WORKSPACE=/absolute/new/notes-v2
export NOTES_WORKSPACE=/absolute/old/notes
export NOTES_PROTECTED_WORKSPACES='[]'

PYTHONPATH=src "$NOTES_PY" -m services.notes_runtime init --workspace "$NOTES_V2_WORKSPACE" --protected-workspace "$NOTES_WORKSPACE"
PYTHONPATH=src "$NOTES_PY" -m services.notes_runtime check
"$NOTES_PY" -m uvicorn main:app --app-dir src --host 127.0.0.1 --port 8000
~~~

如果有补充保护源，初始化时重复传入 --protected-workspace，并在环境的 NOTES_PROTECTED_WORKSPACES 中保留相同项。激活后不能通过删减配置解除已经记录的保护源。

已安装 wheel 的环境也提供 python -m services.notes_runtime 和 main:app，不需要源码 PYTHONPATH 或 --app-dir。G0 已验证新增模块打包、独立安装导入和原有启动方式。

无笔记安全降级：

~~~bash
export ENABLE_NOTES=false
~~~

此模式不打开新旧笔记工作区，任务和报告的 note_status=disabled，note_id 为 null；模型和搜索研究仍可正常执行。它不回退到旧 NoteTool。

## 3. 验证、保护与数据协议边界

[notes_runtime.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/notes_runtime.py:34) 首先校验路径与保护关系，再打开目标。源路径要求真实绝对路径，符号链接别名明确拒绝。保护源仅参与路径比较和路径元数据解析，不由 Repository 打开，不枚举或读取其中的 Markdown。本轮这些源检查全部使用合成临时目录，真实旧笔记未访问。

新目标逐组件沿用 G2a 的 O_DIRECTORY/O_NOFOLLOW 打开方式；源/目标相同、父子嵌套、目录穿越、非绝对路径、缺失目录、目标/祖先符号链接均拒绝。源码布局下的 backend/notes 及其父子关系受额外保护；安装 wheel 后也保留 backend/notes 路径禁用规则，并强制管理员配置真实旧源。

首次 init：

- 目标只能为空目录，允许上次失败留下的合法固定锁文件；在加锁前和锁内分别检查，已有内容或已有标记均拒绝。
- 使用既有 Repository 的真实 flock、同目录原子写入、文件 fsync 和目录 fsync 提交 .files-v2-workspace.json。
- 标记记录 storage、独立的激活格式版本、绝对路径、workspace_id、设备/inode 和保护源清单。
- 不创建笔记、不复制数据、不生成 notes_index.json、不清理已有文件。初始化失败明确返回错误，不伪装成功。

服务启动及每次默认工厂打开时，验证标记字段、绑定路径和目录身份、保留的保护源，再使用原 Repository inspect 检查笔记/控制状态。坏笔记、错误标记、复制标记或替换目录会拒绝；合法手工编辑暂停状态保留，不自动解除。

首次激活要求空目录；后续启动允许同一已激活目录中存在合法笔记。本轮在写入后实际重启 Uvicorn，验证旧的新目录笔记保留，新研究仍得到独立 run_id 和新笔记归属。

G2a/G2b 的 FileNoteRepository、NoteSnapshot/NoteWriteResult、codec、手工窗口、ETag CAS、ReadReceipt、GenerationBasis、NoteOwnership 和幂等算法均未修改。启动检查不会建立模型读取凭据；模型更新仍须使用生成时冻结的 ETag，不会借启动读取或新存储配置获取写入授权。

## 4. 默认服务工厂与 Repository 生命周期

生产入口 main:app 启动时调用 [validate_service_configuration](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/notes_runtime.py:148)，配置错误使 Uvicorn 启动失败。预检句柄在检查结束后立即关闭；启动不保留一个可能被提前关闭的全局 Repository。

请求仍先通过 G4a.1 进程准入，再由 [create_service_agent](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/notes_runtime.py:158)：

1. 按显式服务配置打开已验证 Repository。
2. 使用真实 DeepResearchAgent 构造器传入该 Repository。
3. 为同一 ExecutionControl 注册 on_idle(repo.close)。
4. 构造失败立即关闭本次句柄并保留原准入错误处理。

每次研究拥有一个句柄；不是 HTTP 断开就关闭它。G4a.2 的 producer、监督线程和任务 Worker 仍持有执行引用；引用全部结束后才关闭 Repository 并释放容量。专门验收证明：HTTP 已退出、Fake provider 仍阻塞时 fd 保持打开且同一 Agent 不能重入；放行 provider 后 fd 关闭、容量回收。

Agent 构造器取消了旧 NoteTool 的实例化分支。ENABLE_NOTES=true 而没有 Repository 时立即拒绝；程序化调用应使用服务工厂并传递同一个 execution，或继续由调用者显式注入 Repository。ENABLE_NOTES=false 仍可直接构造。

既有可信 Python agent_factory/显式注入接口继续服务于嵌入及历史 Fake 验收，外部注入的句柄仍归调用者管理。这不是 HTTP 或环境可选择的回退模式；实际默认 main:app 的 files_v2 接线有独立真实启动证据。

## 5. 修改文件与范围核验

环境为 WSL2 注册发行版 Ubuntu22.04.3，Linux 仓库 /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source；每条项目命令先定位并核对 Git 根目录。HEAD 保持 2447fc91d41b3a46a7a4896d216355fad84abbfa，G4a.2 已有未提交改动及用户 Zone.Identifier 均保留。

实施前记录 574 个相关文件指纹，本轮仅 6 个原有文件改变。证据：[baseline.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/baseline.json)、[integrity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/integrity.json)。

| 文件 | 原因 |
|---|---|
| [config.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/config.py:53) | 新增存储选择、新路径、补充保护源字段和 JSON 环境解析 |
| [main.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/main.py:129) | 默认启动预检及真实服务工厂接线，保留研究准入、HTTP/SSE 外观和可信 DI |
| [agent.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:45) | 明确拒绝启用笔记却无 Repository 的路径，移除旧 NoteTool 实例化 |
| [.gitignore](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/.gitignore) | 忽略推荐 backend/notes-v2、激活/锁/维护标记和临时文件 |
| [backend/README.md](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/README.md) | 激活、配置、启动、禁用及回滚操作说明 |
| [G0 验收](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_0_environment.py) | 增加 notes_runtime 的制品和独立安装导入断言，原断言保留 |
| [notes_runtime.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/notes_runtime.py)（新增） | 配置策略、空目录激活、标记验证、服务工厂和 init/check CLI |
| [test_storage_activation.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_storage_activation.py)（新增） | 16 项路径、标记、故障/并发、模式和资源归属验收 |
| [test_storage_activation_lifecycle.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_storage_activation_lifecycle.py)（新增） | 1 项实际默认工厂经 ASGI 取消的句柄生命周期 |
| [test_storage_activation_server.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_storage_activation_server.py)（新增） | 5 项真实 Uvicorn 入口验收，含实际重启、拒绝启动及禁用模式 |
| [storage_activation_bootstrap.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/storage_activation_bootstrap.py)（新增） | 仅在测试子进程注入 Fake LLM/Search、阻断外连及禁止旧 NoteTool |
| 本报告及 docs/storage_activation_evidence/（新增） | 实际命令、输出、启动日志、合成事件样本及指纹 |

后端/前端依赖声明和锁文件未改变；没有修改 G2 数据安全模块、HelloAgents 核心循环、Vue 业务文件、HTTP 路径、SSE type 或前端主要字段。既有 G0–G4a.2 阶段报告和证据均保持原字节；历史验收会生成的合成样本先保存、运行后留副本到本阶段并恢复旧字节。

## 6. 真实启动与测试结果

### 6.1 启动路径

[服务验收](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_storage_activation_server.py) 启动的是：

~~~text
Linux Python -B -c <测试引导代码> main:app --app-dir <backend/src> --host 127.0.0.1 --port <临时端口>
~~~

引导代码只替换模型与搜索、设置外连禁止和 legacy NoteTool 禁止断言，再执行真实 uvicorn 模块。没有传入 agent_factory，没有手工向服务注入 Repository，也没有替换服务工厂或 FileNoteRepository。

实际过程：

- CLI init 对空临时目录生成标记，CLI check 验证环境配置。
- Uvicorn 启动后 /healthz 为 200。
- /research 完成两任务研究；/research/stream 再完成一次独立研究。
- 每次研究真实创建两份任务笔记和一份当前 run_id + final_report 报告，报告 draft/persist 复用同一笔记。
- Reporter 确实读取当前任务笔记；SSE 工具 success、任务/报告 note_status、note_id/path 与磁盘内容及归属逐项一致。
- 同一目录已有笔记时重启 Uvicorn，再次成功研究，旧运行与新运行不串用 ID/归属。
- 缺少 mode、未激活目标、保护源目标均在真实启动时退出；ENABLE_NOTES=false 正常启动和研究，笔记状态明确 disabled。
- 合成旧源文件的字节和目录条目保持不变，没有新增旧索引或控制文件。

证据：[actual-startup-workflow.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/actual-startup-workflow.json)、[files-v2.startup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/files-v2.startup.json)、[files-v2-restart.startup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/files-v2-restart.startup.json)、[activation-cli.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/activation-cli.json)、[activation-check.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/activation-check.json)。

这些路径属于已清理的测试临时目录，不是正式运行目录。没有真实收费模型或搜索请求。

### 6.2 失败复现

- [before.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/before.stderr.txt)：先写的 12 项测试因新激活模块/接口尚不存在而报错；这是未实现接线的证据，不将其全部称为原业务缺陷。
- [source-alias-before.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/source-alias-before.stderr.txt)：保护源使用符号链接别名时，单纯字符串比较漏过真实空旧目录，测试确实失败。增加保护源真实路径要求后拒绝，保留断言。
- 激活写入在 before_replace 注入失败时，没有成功标记、没有笔记，允许对仍为空的新目录明确重试；并发初始化只有一个成功，另一方不能替换标记。
- 标记损坏/符号链接、目录替换、保护源删减、坏笔记和非法路径均拒绝；已存在的维护暂停状态不被清除。

全部失败日志保留，没有跳过测试或删除失败断言。

### 6.3 最终结果

| 验收 | 实际结果 |
|---|---|
| 本轮激活/启动 | 22 tests，12.493 秒，OK，退出 0 |
| G0 | 15 tests，12.288 秒，OK，退出 0 |
| G1 | 14 tests，0.046 秒，OK，退出 0 |
| G2a | 23 tests，4.889 秒，OK，退出 0 |
| G2b | 29 tests，1.669 秒，OK，退出 0 |
| G3 后端 | 17 tests，0.355 秒，OK，退出 0 |
| G4a.1 | 25 tests，0.948 秒，OK，退出 0 |
| G4a.2 后端 | 27 tests，1.751 秒，OK，退出 0 |
| G3 前端 | 17 checks，全通过 |
| G4a.2 前端 | 4 checks，全通过 |
| Vue 类型检查 | 退出 0 |
| Vite 生产构建 | 14 modules，退出 0 |
| git diff --check / 暂存 | 通过，暂存为空 |

全部无跳过。日志：[本轮](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/final.stderr.txt)、[G0](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g0.stderr.txt)、[G1](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g1.stderr.txt)、[G2a](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g2a.stderr.txt)、[G2b](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g2b.stderr.txt)、[G3](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g3.stderr.txt)、[G4a.1](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g4a_1.stderr.txt)、[G4a.2](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g4a_2.stderr.txt)、[前端 G3](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/frontend-g3.stdout.txt)、[前端 G4a.2](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/frontend-g4a2.stdout.txt)、[类型检查](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/typecheck.json)、[构建](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/frontend-build.stdout.txt)。

G0 最终使用 venv/g0-x_4o_2v9 的新独立环境构建/安装当前制品，包含新增配置接线模块；依赖检查、独立导入及三种原 Uvicorn 启动方式全部通过。未依赖 backend/.venv 额外手工包。证据：[g0-commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g0-commands.json)、[g0-setup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g0-setup.json)、[g0-installed-environment.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g0-installed-environment.json)、[g0-http-smoke.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g0-http-smoke.json)、g0-logs/。

前端构建输出 venv/storage-activation-front-mrkvf8ti/dist，未覆盖用户原 dist。已有弃用提示与 Vite 独立 outDir 不自动清空提示未扩大处理。

## 7. 复跑与兼容性

在指定 WSL 内，从已核验的仓库运行：

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
SA_ROOT="$PWD"
SA_PY="$SA_ROOT/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"
SA_FRONT="$SA_ROOT/code/chapter14/helloagents-deepresearch/frontend"
SA_NODE=/home/nhzj121/.nvm/versions/node/v24.15.0/bin/node

"$SA_PY" -B -m unittest discover -s tests/acceptance -p 'test_storage_activation*.py' -v
"$SA_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_1*.py' -v
"$SA_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2a*.py' -v
"$SA_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2b*.py' -v
"$SA_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_4a_1*.py' -v
"$SA_NODE" "$SA_FRONT/tests/acceptance/phase3.mjs"
"$SA_NODE" "$SA_FRONT/tests/acceptance/phase4a2.mjs"

SA_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
env -u G0_WORK_ROOT -u PYTHONPATH -u VIRTUAL_ENV G0_BASE_PYTHON="$SA_BASE" G0_UV=/home/nhzj121/.local/bin/uv "$SA_BASE" -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v
(
 cd "$SA_FRONT" &&
 test "$(git rev-parse --show-toplevel)" = "$SA_ROOT" &&
 "$SA_NODE" node_modules/vue-tsc/bin/vue-tsc.js --noEmit
)
~~~

G3 和 G4a.2 Python 回归的精确命令分别在 [g3.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g3.json)、[g4a_2.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/g4a_2.json)。它们会生成旧阶段的合成样本，本轮先保存后恢复；需要保护原证据时复跑也应这样处理。本轮新样本仅写本阶段目录。其他命令与退出码在同名 JSON；构建独立路径见 [frontend-build.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/storage_activation_evidence/frontend-build.json)。

兼容性变化是明确的：

- HTTP/SSE 请求、路径、事件和前端字段保持原接口。
- 旧的“默认 ENABLE_NOTES=true + ./notes”启动行为停止；必须显式 files_v2、新目录激活、绝对保护源，或明确禁用笔记。
- NOTES_WORKSPACE 不再是运行写入目标；新目标必须用 NOTES_V2_WORKSPACE。
- 原 main:app、--app-dir src、源目录和 wheel 启动形式保留；前提是满足新存储配置或使用无笔记模式。
- 服务工厂产生的 Agent/句柄属于一次研究执行；不要把已经结束并关闭句柄的服务 Agent 当作可复用单例。程序化长期复用仍可沿原显式 Repository 注入方式由调用者管理。

## 8. 回滚及尚未完成的发布条件

不需要数据迁移回滚。尚无新写入时可停止服务并保留候选目录；已有新写入时，先停止接纳、等待实际后台工作 idle，再保留整个新目录及其标记。不能把旧快照覆盖新目录、自动合并回保护源、清理标记后重新初始化或恢复旧不安全 NoteTool 写入。

最直接的安全降级为 ENABLE_NOTES=false 并重启服务：继续研究，显示笔记禁用，保留所有新笔记。若回退代码，应成套回退本轮配置/工厂接线，保留 G2/G3/G4 的安全与状态修复及用户修改；不要使用全仓库 reset/clean。

剩余发布条件：

1. 本轮没有选择、初始化或修改真实正式目录及现有 .env。正式启用仍需管理员核对真实旧源清单，选择空新目录，明确 init/check 后配置并启动。
2. 运行期间不能移动、替换或挂载重绑定工作区；标记不能复制到另一个目录。手工 Markdown 编辑继续遵守 G2a ETag/暂停窗口边界。
3. 保护清单只覆盖明确声明的真实路径与项目保留路径；不能替管理员发现未声明的所有历史数据位置。符号链接路径拒绝，不扩展为多主机或任意挂载别名的数据盘审计。
4. 文件锁与原子写入仍按单机 Linux 文件系统语义；没有新增网络文件系统支持或真实断电证明。
5. 断连/取消仍是协作机制，进程停服前的后台收尾、真实提供商/代理链、真实模型质量及费用停止不由 Fake 验收证明。
6. G5 依赖升级、安全审计和发布门尚未执行；G4b/G6 未实施。本轮接线和启动通过不等于已经具备生产发布结论。

本任务完成后停止，等待 G5 指令；没有自动提交或推送。
