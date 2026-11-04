# G0 可重建环境与依赖基线：实施结果

日期：2026-11-02（Asia/Shanghai）。范围：仅实施改造方案 G0，未提前实施 G1/G2 或后续业务改造。

**结论：G0 在本次 WSL2/Linux + CPython 3.12.14 环境中验收通过。最终 15 项测试全部通过，0 失败、0 错误、0 跳过；没有 G0 遗留问题阻碍启动 G1。**

## 1. 修改范围与原因

仓库根目录 R：`/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source`。后端 B：`R/code/chapter14/helloagents-deepresearch/backend`。

| 文件 | 修改原因 |
|---|---|
| [pyproject.toml](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/pyproject.toml) | 用 py-modules 声明 agent/config/main/models/prompts/utils，自动发现 src 下实际包，排除测试及 egg-info；修复查找不存在 src/src 的打包问题。补充 huggingface-hub==2.3.0、PyYAML==6.0.3 的直接声明；固定已验证的构建后端 setuptools==84.2.1、wheel==0.48.0。 |
| [uv.lock](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/uv.lock) | 按新声明在独立源码副本中解析并回写，形成闭合运行依赖；不对原 .venv 做 sync。hello-agents 仍为 0.2.9，原 FastAPI/OpenAI 等研究运行库未做无关升级。 |
| [README.md](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/README.md)（新增） | 记录独立环境安装、保留的启动入口、G0 验收运行方式和边界。补齐 pyproject 指向的 README 文件。 |
| [tests/acceptance/test_phase_0_environment.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_0_environment.py)（新增） | 真实隔离构建/安装、Fake HTTP、真实本机健康检查与文件系统能力测试。仅测试代码，不是 G2 Repository 实现。 |
| [docs/g0_evidence](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence)（新增目录） | 保存初始指纹、命令、锁差异、最终环境/测试/构建日志、范围核验。 |
| 本报告（新增） | 汇总实际执行结果与复跑方法。 |

Planner、Search、Summarizer、Reporter、NoteTool、main.py、agent.py、config.py、models.py 和前端业务文件均未修改。既有审计报告、改造方案、原测试脚本、AGENTS.md 和所有已有未跟踪审计文件保留。未提交、暂存或推送 Git。

## 2. 环境与隔离证明

| 项目 | 实际结果 |
|---|---|
| Git 基线 | main，755ae75958e6fb072c8a075bcbc55ad15d98bb17；开始时已跟踪文件干净，保留原有未跟踪 AGENTS.md/docs |
| WSL 注册名 | Ubuntu22.04.3 |
| WSL 版本 | 2，Windows 侧 wsl.exe --list --verbose 确认 |
| Linux 系统 | /etc/os-release：ID=ubuntu，VERSION_ID=22.04 |
| 内核 | 6.18.54.1-microsoft-standard-WSL2 |
| 基础 Python | 3.12.14，使用 uv 管理的基础解释器，未使用原 .venv 的包 |
| uv | 0.12.7 |
| SQLite / Node / npm | 3.53.1 / v24.15.0 / 11.12.1；只记录版本，不改前端依赖 |
| 构建隔离 | uv build 默认 PEP 517 隔离构建环境，构建工具固定 84.2.1 / 0.48.0；原源码不直接构建 |
| 最终独立运行环境 | R/venv/g0-20261102-bd5dab4b/acceptance-final/runtime |
| 空环境证明 | 安装前 importlib.metadata.distributions() 为 []；include-system-site-packages=false |
| 导入证明 | -I 模式、无源码 PYTHONPATH、无用户 site；业务模块与 HelloAgents/HF/PyYAML 均从新 runtime/site-packages 导入 |
| 运行保护 | Fake coordinator；真实 LLM 初始化、真实 SearchTool.run、真实 NoteTool 初始化被禁止；外部 socket/DNS 受 guard 限制，仅健康检查允许 loopback |
| 笔记保护 | 没有读取、复制、创建或修改既有笔记工作区。测试 NOTES_WORKSPACE 指向临时不存在的 sentinel，运行后仍不存在 |

没有比较 WSL_DISTRO_NAME 与 Ubuntu VERSION_ID。测试另用注册名 research-dev、VERSION_ID=22.04 验证名称差异不影响能力判定，也验证“名称相似但缺能力”必须失败。

独立环境与 wheel/sdist 保留在已有 .gitignore 覆盖的根目录 venv/ 下，未把验证环境加入 Git。公开包缓存可以复用，但没有将原 .venv 的安装包、site-packages 或手工补包目录作为构建/安装输入。

证据：[docs/g0_evidence/setup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/setup.json)、[docs/g0_evidence/identity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/identity.json)、[docs/g0_evidence/installed-environment.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/installed-environment.json)、[docs/g0_evidence/wsl.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/wsl.json)。

Node 最初用非交互式 WSL 的 PATH 探测时发生 FileNotFoundError：现有 NVM 未自动载入。随后使用已存在的 `/home/nhzj121/.nvm/versions/node/v24.15.0/bin` 显式运行 Node/npm，均退出 0；未安装或更改配置。该失败属于额外版本探测，不是被跳过的验收测试。Python/SQLite/uv/Node/npm 的精确命令见 [docs/g0_evidence/toolchain.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/toolchain.json)。

## 3. 依赖与锁文件的具体变化

### 3.1 直接依赖和构建工具

- hello-agents==0.2.9 保持。
- huggingface-hub==2.3.0 从“原环境额外安装”变为明确声明与锁定的启动依赖，修复普通 import hello_agents 所触发的缺包路径；不启用 evaluation extras。
- PyYAML==6.0.3 变为直接声明，保持原锁版本；此处不实施后续笔记 codec。
- setuptools==84.2.1、wheel==0.48.0 是构建依赖，只进入隔离构建环境；独立运行环境中没有手工安装这两个构建包。

### 3.2 为什么 click 和 idna 发生变化

不是为 G5 做无关升级：

- huggingface-hub 2.3.0 的基本依赖要求 click>=8.4.2,<9，原锁 click 8.3.0 不满足，解析为 8.5.0。
- 其新引入的 httpx2 2.16.0 要求 idna>=3.18，原锁 3.11 不满足，解析为 3.20。

新增 filelock、fsspec、hf-xet、httpx2/httpcore2、packaging、truststore 等为该启动依赖的传递闭包；锁文件还包含其他 Python/平台的条件分支，不表示所有分支包都安装在本次 Linux 运行环境。

uv 0.12.7 将锁文件 revision 从 5 序列化为其支持的 3，lock version 仍为 1；新锁的 --check --offline 已通过。没有自行升级 uv 工具。

完整差异和已安装 METADATA：[docs/g0_evidence/lock-diff.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/lock-diff.json)、[docs/g0_evidence/dependency-reasons.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/dependency-reasons.json)。运行环境按导出的带哈希锁定需求安装，随后 uv pip check 成功；全部已安装发行版版本均能在锁文件中对应。

## 4. 实际构建、安装和测试命令

### 4.1 本次完整验收入口

从 WSL 中的 R 目录执行，基础解释器显式指定：

```bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1

G0_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
G0_UV=/home/nhzj121/.local/bin/uv

env -u G0_WORK_ROOT -u PYTHONPATH -u VIRTUAL_ENV \
  G0_BASE_PYTHON="$G0_BASE" G0_UV="$G0_UV" \
  "$G0_BASE" -B -m unittest discover \
  -s tests/acceptance -p 'test_phase_0*.py' -v
```

复跑入口会创建新的独立目录，不复用已经装包的验证环境。测试控制器使用 stdlib unittest 和 Python 3.11+ 的 tomllib；本次实际使用/验证 3.12.14。

本次最终执行额外显式设置 G0_WORK_ROOT 为 R/venv/g0-20261102-bd5dab4b/acceptance-final。精确 argv、cwd、环境选择与用时保存在 [docs/g0_evidence/test-command-final.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/test-command-final.json) 和 [docs/g0_evidence/test-process-final.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/test-process-final.json)。

### 4.2 验收内部已执行的构建/安装步骤

以下是本次执行的步骤记录；路径已存在，不应当作“清空并重建同一环境”的操作指令。复跑请使用上一节入口。

```bash
# WORK = R/venv/g0-20261102-bd5dab4b/acceptance-final
# SOURCE = WORK/source（只复制 pyproject、锁、README、干净 src）
# ENV = WORK/runtime（新建，安装前无任何发行版）
# BASE = 上一节的基础解释器；UV = /home/nhzj121/.local/bin/uv

"$UV" lock --project "$SOURCE" --python "$BASE" --check --offline
"$UV" build --project "$SOURCE" --python "$BASE" --out-dir "$WORK/artifacts"
"$UV" venv --python "$BASE" "$ENV"

"$UV" export --project "$SOURCE" --locked --no-dev --no-emit-project \
  --format requirements-txt --output-file "$WORK/runtime-requirements.txt"

"$UV" pip install --python "$ENV/bin/python" --require-hashes --no-deps \
  -r "$WORK/runtime-requirements.txt"
"$UV" pip install --python "$ENV/bin/python" --no-deps \
  "$WORK/artifacts/helloagents_deep_researcher-0.0.1-py3-none-any.whl"
"$UV" pip check --python "$ENV/bin/python"
```

使用 --no-deps 安装完整锁导出后，再执行 pip check 验证闭包，避免安装器从未声明的旧环境中“补齐”依赖。wheel 是普通安装，不是 editable 安装；导入验证从无关工作目录以 Python -I 运行。

所有构建均在源副本中进行，sdist 和 wheel 均成功。wheel 包含六个平铺模块与 services 的全部八个 Python 文件，不再寻找 src/src；sdist 包含 README、pyproject 和所有对应源码。

完整展开命令：[docs/g0_evidence/commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/commands.json)；构建日志：[docs/g0_evidence/logs/build.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/logs/build.stderr.txt)；安装日志：[docs/g0_evidence/logs/install-runtime-dependencies.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/logs/install-runtime-dependencies.stderr.txt)、[docs/g0_evidence/logs/install-wheel.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/logs/install-wheel.stderr.txt)；闭包检查：[docs/g0_evidence/logs/dependency-check.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/logs/dependency-check.stderr.txt)。

## 5. 实际测试结果

最终结果：`Ran 15 tests in 14.841s — OK`。整个最终测试进程约 15.094 秒，退出码 0。没有 skip 或通过忽略失败获得的成功。

初次 14 项测试也通过；随后补充“源码副本排除私人配置/环境并保留代码”的测试与排除规则，再用另一个全新环境完整执行最终 15 项。初次输出保留，没有覆盖为最终结果。

| 测试 | 结果与验证内容 |
|---|---|
| 注册名与 OS 版本独立 | 通过；research-dev 与 22.04 可以同时有效，缺目录 fsync 能力则失败 |
| 跨进程 flock | 通过；父进程持锁时子进程 nonblocking 获取失败，释放后成功 |
| dir_fd / O_NOFOLLOW | 通过；相对目录 fd 文件访问正常，临时 symlink 被拒绝 |
| 原子替换并发读取 | 通过；40 次替换中读者只见完整旧/新内容，没有半文件 |
| 目录 fsync | 通过；临时文件与目录描述符 fsync 实际执行成功 |
| 源码副本保护 | 通过；未复制 .env/原环境/notes，Python 源码字节保持 |
| wheel 内容/元数据 | 通过；六个模块、services、依赖与固定构建工具声明正确 |
| sdist 内容 | 通过；README、pyproject、源码完整，无环境/笔记 |
| 安装后独立导入 | 通过；模块来自新环境，无原 source/旧 .venv 包回退 |
| 运行依赖与 lock | 通过；空环境起步，版本对应，uv pip check 退出 0 |
| Fake HTTP 路由 | 通过；healthz、/research、/research/stream 正常；Fake 异常产生 error 帧 |
| 已安装 Uvicorn 启动 | 通过；无源码 PYTHONPATH/--app-dir，在无关目录 healthz=200 |
| 原 --app-dir src 方式 | 通过；源码副本 + 新运行环境，healthz=200 |
| 原 src 工作目录方式 | 通过；源码副本 src 目录 + 新运行环境，healthz=200 |
| 原文件/环境保护 | 通过；除 pyproject 和锁外所有原始指纹保持，原 .venv 元数据保持 |

日志：[docs/g0_evidence/acceptance-final.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/acceptance-final.stderr.txt)；文件系统结果：[docs/g0_evidence/capabilities.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/capabilities.json)；HTTP 结果：[docs/g0_evidence/http-smoke.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/http-smoke.json)。

文件系统探针只验证当前 Linux 文件系统提供后续需要的基础能力，不提供 G2 的并发存储、掉电恢复、ETag 或手工编辑保证；没有新增 Repository 或改动 NoteTool。

## 6. 启动兼容性

三种方式都由真实 Uvicorn CLI 启动并以本机 HTTP /healthz 验证；启动保护禁止真实模型、搜索及笔记工具初始化/执行：

1. 安装 wheel 后，从无关目录运行 main:app，不用源码路径。
2. 后端目录形态下，main:app --app-dir src。
3. 进入 src 工作目录后运行 main:app。

对应日志：[docs/g0_evidence/logs/startup-installed.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/logs/startup-installed.txt)、[docs/g0_evidence/logs/startup-app-dir.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/logs/startup-app-dir.txt)、[docs/g0_evidence/logs/startup-src-cwd.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/logs/startup-src-cwd.txt)。每个自建进程在健康检查成功后由测试停止并等待退出；这不是启动失败或残留服务。

原 `python src/main.py` 的 main.py 字节未变，原 reload/bind 参数保留；为避免启动额外 reloader 和原固定端口，本次没有单独运行这个脚本形态。也没有增加 .env 自动加载或改变既有配置来源。

/research 与流式请求使用 Fake coordinator 验证路由/序列化，不代表真实 Planner/Search/Summarizer/Reporter 已经正确执行；A01 等业务缺陷保持原样，留给 G1。

## 7. 非失败提示与验证边界

- 构建输出有既存 project.license TOML table 的 setuptools 弃用警告。当前构建成功，未因警告跳过测试；本次不为消除非阻塞提示改动许可证语义。
- 日志中的 byte-compiling disabled 来自验证环境 PYTHONDONTWRITEBYTECODE=1，不是漏包；wheel 内容与导入已经实际验证。
- 当前验证为 Linux/WSL2 + Python 3.12.14 + uv 0.12.7。继承的 requires-python>=3.10 范围保留，锁文件含相应解析分支，但没有声称对所有 Python/平台都完成运行验收。
- 共享基础解释器不等于共享原 .venv 包。安装前空发行版、系统 site 关闭、-I 和实际 __file__/sys.path 证明了隔离；下载缓存复用不改变这一点。
- 没有调用真实付费 API，没有执行研究质量、实际服务商取消、G2 数据迁移或 S01 前端安全升级。frontend package/lock 未改。
- 依赖下载、锁解析成功，无失败阻塞；测试没有被跳过。后续远端网络不可用时应如实报告安装阻塞，不能改用旧 .venv 掩盖问题。

## 8. G0 判定、回滚与 G1 交接

| G0 验收门槛 | 结论 |
|---|---|
| A15 打包失败：wheel/sdist、完整模块与 services、README | 通过；实际隔离构建和制品内容检查 |
| A16 声明与锁不足：新环境安装、普通导入、依赖闭合 | 通过；空环境、带哈希安装、pip check、独立导入 |
| Fake /healthz、同步与流式入口、错误帧 | 通过；真实研究能力留待后续阶段 |
| 注册名、OS/WSL/Python/SQLite/Node/包管理器分别记录 | 完成；不以注册名与 OS 版本相等作为门槛 |
| Linux flock / dir_fd / O_NOFOLLOW / replace / 目录 fsync | 通过；全部在临时路径实际执行 |
| 原源码、旧环境、既有文档和笔记保护 | 通过；101 个原有指纹中仅 2 个授权文件改变；测试未访问既有笔记 |
| G0 范围与回滚 | 保留旧 .venv/前端环境，未实施后续阶段，未提交或推送 |

**是否阻碍 G1：没有发现 G0 遗留的构建/安装/导入/基础文件系统阻碍。** 可以在用户下达 G1 指令后继续。G1 仍需按方案处理 A01/A02/A03/A04/A11/A19 和 R05；目前不应对真实笔记启用未经 G2 验证的并发写入。

回滚只需恢复本次 pyproject/锁文件到保存的基线版本并选择原环境；原 .venv 未被卸装。不要用 git reset --hard 或清理未跟踪文件回滚，因为其中包含用户原有 AGENTS.md 和审计文档。验证环境与构建产物独立保留，移除它们也不能触碰原 notes/。

范围指纹与 Git 状态见 [docs/g0_evidence/integrity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g0_evidence/integrity.json)。G0 到此停止；没有自动提交、推送、实施 G1/G2 或进行任何笔记迁移。
