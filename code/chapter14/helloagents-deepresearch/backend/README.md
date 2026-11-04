# HelloAgents DeepResearch 后端运行手册

本手册描述当前 G0–G5 与 files_v2 接线后的行为。保留 Planner → Search → Summarizer → Reporter 工作流；原 NoteTool 不再是服务的隐式回退路径。

## 1. 已验收环境与公共变量

已验收：单机 WSL2/Linux，WSL 注册名 Ubuntu22.04.3（与 Ubuntu VERSION_ID=22.04 分开记录）、CPython **3.12.14**、uv **0.12.7**。前端使用 Node **24.15.0** / npm **11.12.1**。包声明的 Python >=3.10 不代表其他版本已验收。文件锁、原子替换和目录 fsync 按本地 Linux 文件系统验证，不扩展为 NFS/多主机保证。

每个后端终端先执行以下公共块；所有操作都在 WSL 内。不要在 Windows 入口目录开发或安装。

~~~bash
DR_ROOT=/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
cd "$DR_ROOT" || exit 1
test "$(git rev-parse --show-toplevel)" = "$DR_ROOT" || exit 1
DR_BACKEND="$DR_ROOT/code/chapter14/helloagents-deepresearch/backend"
DR_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
DR_UV=/home/nhzj121/.local/bin/uv
"$DR_BASE" -c 'import sys; assert sys.version_info[:3] == (3,12,14); print(sys.version)' || exit 1
"$DR_UV" --version || exit 1
~~~

这些工具路径对应本机现有安装；其他 Linux 主机须改为其实际路径并保持相同验收版本。不要自动安装另一套系统 Python 代替核对。

## 2. 安装到独立的新环境

已建立的 backend/.venv 不需要被重装。下面在根 venv/ 下创建唯一新环境，使用当前锁文件，不修改依赖或锁：

~~~bash
cd "$DR_ROOT" || exit 1
test "$(git rev-parse --show-toplevel)" = "$DR_ROOT" || exit 1
mkdir -p "$DR_ROOT/venv" || exit 1
DR_ENV="$(mktemp -d "$DR_ROOT/venv/deepresearch-runtime-XXXXXX")" || exit 1
(
  cd "$DR_BACKEND" || exit 1
  test "$(git rev-parse --show-toplevel)" = "$DR_ROOT" || exit 1
  UV_PROJECT_ENVIRONMENT="$DR_ENV" "$DR_UV" sync --locked --no-dev --python "$DR_BASE"
) || exit 1
DR_PY="$DR_ENV/bin/python"
"$DR_PY" --version
"$DR_UV" pip check --python "$DR_PY" || exit 1
printf '本次服务解释器：%s\n' "$DR_PY"
~~~

保留打印出的 DR_PY，后续统一用它，避免 uv run 意外选择其他环境。新开终端时重设公共变量，再将 DR_PY 指向已选环境；不要每次重建。hello-agents 保持 0.2.9，运行依赖以 uv.lock 为准。G0 的 wheel/sdist 与完整锁导出验收仍可独立复跑。

## 3. 启动前必须选择一种笔记模式

| 项目 | 无笔记模式 | files_v2 安全笔记模式 |
|---|---|---|
| ENABLE_NOTES | 显式 false | 显式 true |
| NOTES_STORAGE | 不需要 | 必须精确 files_v2 |
| NOTES_V2_WORKSPACE | 不打开 | 已激活的新目标的绝对 Linux 路径 |
| NOTES_WORKSPACE | 不打开 | 原笔记保护源的真实绝对路径，仅作保护 |
| NOTES_PROTECTED_WORKSPACES | 不需要 | 其他保护源的 JSON 路径数组，默认 [] |
| 输出 | 研究照常；任务/报告 note_status=disabled，无成功 note_id | 研究与笔记状态分别显示，保存失败不能冒充成功 |

默认 ENABLE_NOTES=true，而默认存储未选择；**直接裸启动会拒绝**。没有自动降级成旧 NoteTool，也没有自动迁移或默认写入 backend/notes。

### A. 无笔记模式：先验证启动

~~~bash
cd "$DR_ROOT" || exit 1
test "$(git rev-parse --show-toplevel)" = "$DR_ROOT" || exit 1
test -x "$DR_PY" || exit 1
export ENABLE_NOTES=false
unset NOTES_STORAGE NOTES_V2_WORKSPACE NOTES_WORKSPACE NOTES_PROTECTED_WORKSPACES
PYTHONPATH="$DR_BACKEND/src" "$DR_PY" -m services.notes_runtime check
~~~

预期输出 storage=disabled。这个检查和 /healthz 不调用模型/搜索；提交研究请求仍会使用所配置的真实服务。无笔记模式不需要查看或修改任何旧笔记。

### B. files_v2：仅首次初始化独立空目录

先由管理员明确保护源清单。所有路径必须是无符号链接、无 . 或 .. 的真实绝对 Linux 路径；新旧目录不得相同或互为父子。以下命令由操作者执行，本次工程收尾不会替你选择或操作真实旧目录。

~~~bash
cd "$DR_ROOT" || exit 1
test "$(git rev-parse --show-toplevel)" = "$DR_ROOT" || exit 1
test -x "$DR_PY" || exit 1
read -r -p '旧笔记保护源的真实绝对路径：' NOTES_WORKSPACE
export NOTES_WORKSPACE
export NOTES_PROTECTED_WORKSPACES='[]'
DR_NOTES_PARENT="$HOME/.local/share/deepresearch"
mkdir -p "$DR_NOTES_PARENT" || exit 1
NOTES_V2_WORKSPACE="$(mktemp -d "$DR_NOTES_PARENT/notes-v2-XXXXXX")" || exit 1
export NOTES_V2_WORKSPACE
export ENABLE_NOTES=true
export NOTES_STORAGE=files_v2
PYTHONPATH="$DR_BACKEND/src" "$DR_PY" -m services.notes_runtime init \
  --workspace "$NOTES_V2_WORKSPACE" --protected-workspace "$NOTES_WORKSPACE" || exit 1
PYTHONPATH="$DR_BACKEND/src" "$DR_PY" -m services.notes_runtime check || exit 1
printf '请保存此新工作区路径：%s\n' "$NOTES_V2_WORKSPACE"
~~~

有额外保护源时，首次 init 还必须逐个追加 --protected-workspace /absolute/other/source，且 NOTES_PROTECTED_WORKSPACES 填相同路径的 JSON 数组；不要用默认 [] 覆盖已有保护清单。

init 要求显式存在的空新目录，只写激活标记，不复制笔记。保护源只参与路径元数据及重叠判断，不打开其中 Markdown。目标缺失/非空、无效选择、保护源重叠、符号链接、无效标记或坏格式均明确拒绝，不能静默退回旧工具。

**重启用已有 files_v2 目录时不再 init/mktemp。** 重新导出 ENABLE_NOTES、NOTES_STORAGE、保存的 NOTES_V2_WORKSPACE、原 NOTES_WORKSPACE 和完整额外保护清单，再执行 check。标记绑定绝对路径、设备/inode；不要重命名、替换、重新挂载目标或复制标记到别处，不能删减既定保护源。正常已有合法笔记可以重启使用。

普通手工保存后下一次读取可见；ETag 会拒绝过期更新，但不参加锁的编辑器仍有“检查后保存/原子替换”的竞争，非原子保存还可能暴露不完整正文。要求无覆盖或批量编辑时，使用高安全暂停窗口，仅对上述新工作区运行：

~~~bash
cd "$DR_ROOT" || exit 1
test "$(git rev-parse --show-toplevel)" = "$DR_ROOT" || exit 1
"$DR_PY" "$DR_BACKEND/scripts/notes_admin.py" manual-begin --workspace "$NOTES_V2_WORKSPACE" || exit 1
# 等成功返回后开始编辑；妥善保存返回的 session_token。完成全部保存后：
read -r -p '返回的 session_token：' DR_EDIT_TOKEN
"$DR_PY" "$DR_BACKEND/scripts/notes_admin.py" manual-end --workspace "$NOTES_V2_WORKSPACE" --token "$DR_EDIT_TOKEN"
~~~

begin 后写入被拒绝、读取仍可进行；end 验证失败保持暂停。重启不会自动解锁，不得删除控制文件绕过恢复。发生 COMMIT_UNCERTAIN 时先检查，不盲目重试。ETag、ReadReceipt、GenerationBasis、可信 run/task/purpose 和报告幂等协议保持原样。

## 4. 模型和搜索配置

服务不自动加载 .env；由同一终端或可信启动器实际导出环境变量，不改正式凭据文件。仅健康检查可不配置提供商；研究前必须配置可用模型/搜索。以下为**人工真实服务验证**，请求可能收费，本轮未执行：

~~~bash
cd "$DR_ROOT" || exit 1
test "$(git rev-parse --show-toplevel)" = "$DR_ROOT" || exit 1
export LLM_PROVIDER=custom
read -r -p 'OpenAI 兼容 base URL（通常包含 /v1）：' LLM_BASE_URL
read -r -p '模型 ID：' LLM_MODEL_ID
read -r -s -p 'LLM API key：' LLM_API_KEY
printf '\n'
export LLM_BASE_URL LLM_MODEL_ID LLM_API_KEY
export SEARCH_API=tavily
read -r -s -p 'Tavily API key：' TAVILY_API_KEY
printf '\n'
export TAVILY_API_KEY
~~~

密钥不回显，不把终端环境转储到验收报告。若使用已部署的本地 Ollama，设 LLM_PROVIDER=ollama、LOCAL_LLM=已安装模型、OLLAMA_BASE_URL=http://localhost:11434；LM Studio 使用 LLM_PROVIDER=lmstudio、LOCAL_LLM 和 LMSTUDIO_BASE_URL（默认 http://localhost:1234/v1）。本地模型并不使外部搜索自动离线。SEARCH_API 支持 duckduckgo/tavily/perplexity/searxng/advanced；各后端的实际可达性和授权需人工验证。

可调整执行默认值：

| 环境变量 | 默认 | 含义 |
|---|---|---|
| MAX_TASK_WORKERS | 3 | 每研究同时活跃任务上限 |
| MAX_ACTIVE_RESEARCH | 2 | 每服务进程准入；多进程按进程数相乘 |
| MAX_PLANNED_TASKS | 8 | 超量规划明确拒绝，不静默裁剪 |
| RESEARCH_DEADLINE_SECONDS | 180 | 协作 deadline，不是同步请求强制终止时限 |
| MODEL_CONNECT_TIMEOUT / MODEL_READ_TIMEOUT | 5 / 20 秒 | 每次连接/读取等待上限，受剩余预算约束 |
| MODEL_MAX_RETRIES | 1 | 最多额外重试次数；已输出的流不重放 |

## 5. 启动、健康检查与接口

完成模式 check 后，在同一环境以前台、单进程、无 reload 方式启动，便于记录和停止：

~~~bash
cd "$DR_ROOT" || exit 1
test "$(git rev-parse --show-toplevel)" = "$DR_ROOT" || exit 1
test -x "$DR_PY" || exit 1
"$DR_PY" -m uvicorn main:app --app-dir "$DR_BACKEND/src" --host 127.0.0.1 --port 8000
~~~

另一个 WSL 终端核验（无模型调用）：

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source || exit 1
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
curl --fail http://127.0.0.1:8000/healthz
~~~

应为 {"status":"ok"}；这只证明应用启动，不证明提供商或研究质量。原 backend/src 工作目录下的 main:app 入口仍可用。安装当前 wheel 后可从其他目录启动 main:app，无需 --app-dir；仍须相同环境变量。源码脚本 python src/main.py 自带 reload/0.0.0.0，不作为本手册的验收启动命令。

HTTP 路径不变：GET /healthz，POST /research（JSON），POST /research/stream（SSE）。请求仍为 topic 与可选 search_api。SSE 保留原 type 与主要字段；done 不等于研究成功，必须检查 run_status、任务 status、独立 note_status/error/warnings。研究容量满返回 429；流中的 error 或没有终止帧的 EOF 不应当成成功。

## 6. 前端与 G5 之后的安装

前端实际配置端口 **5174**，默认请求 http://localhost:8000。详细安装见根 README。G5 更新过 package-lock.json，**原 node_modules 未被替换，必须按新锁重新 npm ci --ignore-scripts**；不要沿用旧安装或用 npm install 重新漂移依赖。当前已验收 Node 24.15.0/npm 11.12.1，npm run build 包含 Vue/TS 类型检查。VITE_API_BASE_URL 是 Vite 启动/构建时变量，变更后须重启 dev server 或重新构建。

## 7. 停止与安全回滚

1. 先停止提交新研究；让正常请求完成。取消请求后，确认已开始的 provider/搜索实际返回并完成清理，再替换执行器或工作区。
2. 前端终端 Ctrl+C 停止 Vite；后端终端 Ctrl+C 请求 Uvicorn 正常停止并等待进程退出。本手册不使用 kill -9、reload 或批量杀进程。
3. **目前没有公开 idle/drain 状态 API 或保证 daemon 后台线程排空的停服协议。** /healthz、done、浏览器 Abort、HTTP 已退出、甚至 Uvicorn 进程退出，都不能证明远端模型已停止生成/计费。若日志和提供商记录无法确认收尾，保持目录原位、不启动并排替代执行器，记录残余状态并人工处理；这仍是部署验收边界。
4. 降级：完成收尾后，按第 3 节 A 设置 ENABLE_NOTES=false，check 后重启。保留新工作区及标记/笔记，不写回保护源，不恢复 unsafe NoteTool。
5. 恢复安全笔记：保留原绝对路径和完整保护清单，重新导出 files_v2 配置，check 通过后启动；已有目标不再 init。不能以旧快照覆盖新提交，也不能把带标记备份复制到另一路径当成已激活工作区。数据恢复/迁移须另行设计。
6. 代码/前端版本回退要成套选择已验收版本、manifest/lock、独立环境及制品，保留 G2–G4 安全机制和用户改动；不能 reset/clean 全仓库。回退 G5 前的依赖会重新引入已知公告，不能按“功能可用”视为安全发布。

## 8. Fake 验收与真实运行准备

不需要真实 key 的完整复跑入口在根 docs/g5_evidence/run_backend_regressions.py：G0 新环境构建/安装，然后按阶段执行 Fake/Mock/TemporaryDirectory 验收，自动保留/恢复历史合成证据。单独运行 G3、G4a.2、storage activation 测试会重写其历史样本，需按该控制脚本保护原证据；不要直接覆盖旧报告。

最新工程收尾结果、精确命令和**人工真实 LLM/Search、浏览器、取消验证清单与通过标准**见 [工程收尾报告](../../../../docs/deepresearch_closeout_results.md)。G4b 的总体预算/长时压测及 G6 能力扩展未实施，真实提供商行为和浏览器/代理链不能由 Fake 测试替代。
