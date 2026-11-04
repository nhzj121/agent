# G2a 独立 Markdown Repository 实施结果

日期：2026-11-03（Asia/Shanghai）。

**结论：G2a 23 项通过，G1 14 项通过，G0 15 项通过，全部无跳过。具备进入 G2b 组合式工具适配的前置条件。本阶段未接入 Agent，未切换实际 NoteTool，未访问已有笔记。到此停止。**

## 1. 环境、范围与保护

所有项目操作均在 WSL Ubuntu22.04.3 内执行，实际核对当前目录及 Git 根目录为 /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source。Git main / 755ae75958e6fb072c8a075bcbc55ad15d98bb17，保留 G0/G1 的已有修改、用户根 README/Zone.Identifier、未跟踪 AGENTS.md、docs/ 和 tests/。

开始状态/指纹见 [baseline.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/baseline.json)，结束核验见 [integrity.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/integrity.json)。相对阶段开始，原有文件仅扩展 tests/acceptance/test_phase_0_environment.py 的 storage 包断言。现有 Agent、LLM、Tracker、业务服务、前端、配置、依赖/锁文件和旧报告不变。未暂存、提交、推送或清理用户文件。

所有 G2a 笔记工作区、外部保护文件、符号链接目标、导出目的地、故障/终止进程实验均来自 TemporaryDirectory 和合成内容；没有读取现有 notes/，没有迁移。仅读取框架 note_tool.py 源码来确认旧 writer 的文件格式，未加载或运行 NoteTool。G0 的构建环境仍位于既有忽略规则覆盖的 venv/，不属于笔记测试数据。

## 2. 新增文件及职责

B 表示后端目录 code/chapter14/helloagents-deepresearch/backend。

| 新文件 | 职责 |
|---|---|
| [storage/__init__.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/__init__.py) | 独立存储包，无框架导入 |
| [note_repository.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/note_repository.py) | NoteSnapshot、NoteWriteResult、NoteError、Repository 协议 |
| [file_notes.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/file_notes.py) | 安全目录 fd、ID、跨线程/进程 flock、ETag、提交、派生查询、检查及快照导出 |
| [note_codec.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/note_codec.py) | 专用旧格式读分支、版本化安全 YAML、重复键/别名/未知版本拒绝、正文及未知字段保留 |
| [manual_edit.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/manual_edit.py) | 持久化 begin/end 编辑窗口，token 和 generation 校验 |
| [notes_admin.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/scripts/notes_admin.py) | 显式工作区 CLI：inspect、manual-begin、manual-end、export；无默认 ./notes |
| [test_phase_2a_repository.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_2a_repository.py) | 19 项 Repository、codec、故障、安全、手工编辑与临时切换测试 |
| [test_phase_2a_processes.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_2a_processes.py) | 4 项 spawn 多进程创建、CAS、终止边界与维护窗口测试 |

另扩展 [G0 验收脚本](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_0_environment.py)，确认 wheel/sdist 包含五个 storage Python 文件，且独立安装后可以从新 site-packages 导入。没有改变依赖配置或原 G0/G1 断言。

## 3. 数据结构与公开接口

[NoteSnapshot](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/note_repository.py:19) 为 frozen dataclass，包含：
id、title、note_type、tags（tuple）、content、created_at、updated_at、etag、format_version、绝对 path、extra。未知元数据放在独立拷贝 extra；run_id/task_id/purpose/idempotency_key 有读取属性，但在 G2a 只是元数据，不作为可信归属或写入授权。extra 的嵌套对象不是深度不可变凭据，G2b 必须另建可信 receipt/basis，不能据此提权。

[FileNoteRepository](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/file_notes.py:42) 要求显式、已存在的绝对工作区；不默认初始化目录。使用 with 或显式 close 释放目录 fd；不要在其他线程仍使用该实例时 close，也不要在使用期间重命名工作区或移除锁文件。

| 接口 | 返回/约束 |
|---|---|
| create(fields) | 完整已提交 NoteSnapshot；fields 为 dict：title、content、note_type、tags(list[str])、extra(dict)；不允许传路径/指定 ID |
| read(note_id) | 每次读取磁盘并验证格式，不缓存内容 |
| update(note_id, patch, expected_etag) | 新快照；patch 仅 title/content/note_type/tags，其他字段保持；缺 ETag 返回 READ_REQUIRED |
| delete(note_id, expected_etag) | NoteWriteResult(ok=True, persisted=True, note_id=...)；缺 ETag 拒绝 |
| list() / search(query) | 磁盘派生快照列表；search 对标题/正文/tags 作大小写不敏感包含匹配 |
| summary() | total_notes 与 by_type，全部从当前文件派生 |
| inspect() | issues、paused、generation、total_notes；报告非法条目和旧索引重复/漏项/缺文件 |
| export(destination) | 向显式已存在空目录作逐文件字节保留快照；检查失败或目的地非空时拒绝，不执行在线迁移 |
| ManualEditController.begin()/end(token) | 开启返回 session_token/generation；恢复先验证笔记，再持久化下一 generation |

create/update 成功返回快照意味着本次 file fsync、replace、目录 fsync 已正常返回；失败抛 NoteError(code, detail, persisted)。实现错误包括 INVALID_ID、NOT_FOUND、CONFLICT、READ_REQUIRED、WRITES_PAUSED、FORMAT_ERROR、IO_ERROR、COMMIT_UNCERTAIN。persisted=False 表示本次未进入提交，unknown 表示不能承诺持久状态。工具字符串转换、VERSION_PARAM_MISMATCH、OWNERSHIP_ERROR 与 Agent 可信绑定留待 G2b；本阶段不验证模型生成基线。

## 4. 锁、路径、ETag 与提交

[锁实现](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/file_notes.py:76) 每个操作单独 open 锁文件，使用 Linux flock 的独立 open file description，因此同实例线程、不同实例、不同进程均参加同一锁。读取用共享锁，创建/更新/删除/维护状态用工作区独占锁，不修改既有进程模型。所有协作写入者必须遵守该协议；只承诺单机本地 Linux 文件系统，不宣称分布式/NFS 一致性。

- 新 ID 为 note_加 uuid4 hex；保留 note_YYYYMMDD_HHMMSS_count 旧 ID。独占锁内检查目标，最多尝试 8 次；固定 UUID 碰撞返回 CONFLICT，不覆盖。
- 所有动作校验 ID。工作区从 / 起逐级 O_DIRECTORY/O_NOFOLLOW 打开；笔记、控制/锁文件从目录 fd 相对打开，O_NOFOLLOW/O_NONBLOCK 并验证普通文件及链接数为 1。拒绝 symlink、hardlink、目录/FIFO 等特殊条目。扫描也验证 ID/格式，不跟随符号链接。
- ETag 是完整文件原始字节 SHA-256，包含 frontmatter、正文及手工保存的变化。update/delete 在独占锁内重读并比较调用方 ETag，绝不将新读版本反填 expected_etag，不自动重试。patch 保留未显式改动字段。
- [原子提交](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/storage/file_notes.py:152)：同目录 O_EXCL 临时文件→写入/flush→文件 fsync→os.replace→目录 fsync。编码结果在提交前用同一 codec 验证可读。创建只在锁内确认目标不存在后提交。
- 临时名字碰撞不覆盖或删除已有文件。已创建临时文件尽力清理；异常终止留下的临时文件被查询忽略，不自动采用、修复或启动清理。
- 进入 replace 尝试后失败一律保守报告 COMMIT_UNCERTAIN；即使新内容已可见，也不等于掉电持久性已确认。调用方须重新检查，不能按“确定没写”盲重试。
- delete 在校验后 unlink+目录 fsync；提交阶段失败同样报告不确定。
- inspect 对笔记及旧索引只读。锁协调可能创建内部 .notes.lock；不会初始化 notes_index.json，不自动改名/修复旧条目。

## 5. 手工编辑与维护窗口操作

普通编辑：没有并发写入者时可直接保存；下一次 read 立即读到完整保存的字节，旧 ETag update 冲突。格式不合法时明确报 FORMAT_ERROR，绝不自动重建覆盖。即使元数据合法，部分正文仍可能被当作有效内容，程序无法推断保存是否完整。

普通编辑器不参与 flock/CAS，以下两种竞争仍存在：
1. Agent 比较 ETag 后、replace 前，编辑器保存，随后被 Agent 覆盖。
2. 编辑器基于旧内容打开，Agent 提交后再保存，覆盖 Agent 新内容。
测试用事件屏障实际展示了第一种竞争，断言最终是 agent-save；这不是“安全编辑”通过证明。原子保存只改善文件可见性，不能解决过期覆盖。

高安全或批量编辑必须采用窗口。下面仅说明显式临时副本的操作方式，本次没有对真实工作区运行：

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G2_PY="$PWD/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"
G2_ADMIN="$PWD/code/chapter14/helloagents-deepresearch/backend/scripts/notes_admin.py"
G2_WORKSPACE=/absolute/path/to/temporary-copy

"$G2_PY" -B "$G2_ADMIN" inspect --workspace "$G2_WORKSPACE"
"$G2_PY" -B "$G2_ADMIN" manual-begin --workspace "$G2_WORKSPACE"
# 保存返回的 session_token，等 begin 成功返回后才开始编辑。
# 完成所有保存后，将返回值填入下一变量。
G2_TOKEN='returned-session-token'
"$G2_PY" -B "$G2_ADMIN" manual-end --workspace "$G2_WORKSPACE" --token "$G2_TOKEN"
~~~

begin 等待当前提交结束，在锁内原子持久化 .notes-control.json 的 token/generation，之后所有 Repository 写入返回 WRITES_PAUSED；读取仍可进行。重启不自动恢复。end 核对 token，在锁内检查所有 Markdown 编码、ID、格式；失败保持暂停，不自动改数据。旧索引只是派生参考，end 不以其陈旧内容阻止恢复，但 inspect/export 会明确报告并阻止未经检查的数据切换。

token 需妥善保存。若 begin 报 COMMIT_UNCERTAIN，先 inspect 确认状态，由管理员在同一显式工作区只读核对权限为 0600 的控制文件及其 session_token，再调用正常 end 验证；不能靠删除/改写控制文件跳过校验。控制文件损坏时拒绝写入，未提供自动强制恢复。窗口也不防止编辑器中途保存被读取，必须等完整保存后再 read/end。

## 6. 旧格式、派生查询与数据演练

专用 legacy codec 按原 writer 的逐行 key:first-colon 解析，标题可以包含冒号、Unicode；tags 必须是合法 JSON 字符串数组。保留旧 ID、时间、未知字段和正文，只去除原 writer 的精确空行/标题外壳。读取不写回、不规范化旧文件。显式 update 才转成 format_version=1 的安全 YAML，保留原 ID、created_at、正文和未知字段，更新时间和 ETag。

新版本用 SafeLoader 子类和 safe_dump；拒绝重复键、YAML 别名、未知版本、非法 UTF-8、filename/frontmatter ID 不同或无法无损理解的旧多行元数据。带引号的 format_version 同样识别，不绕过版本校验。

测试结果：
- 含冒号标题、中文、JSON tags、未知字段的合成旧文件读取正确，文件字节不变；显式更新后内容和未知字段保持。
- 旧非法 tags、重复元数据键、未知版本（含引号）、ID 不匹配、坏编码均明确报错，源字节不变。
- notes_index.json 重复 ID、缺文件、漏索引均由 inspect 报告，export 拒绝；list/search/summary 仍从文件派生。删除临时索引后正常读取，未重建索引。
- 临时保护源→空副本导出，先验证字节相等，再只改候选副本；选择候选读取新值，切回保护源读取旧值，候选新值仍保留。源笔记字节全程不变。
- export 不复制旧索引或维护状态，不转换回 unsafe NoteTool 格式；它是本 Repository 的 Markdown 快照。目标非空拒绝；中途失败可能留部分副本，不清理、不覆盖已有目的地。不是跨文件原子迁移。

## 7. 测试过程、故障注入与回归

先编写两个测试模块，再实现 storage：首次为两个 ModuleNotFoundError，记录在 [before.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/before.stderr.txt)。这是新接口的 TDD 红灯，不声称这次对现有 NoteTool 重新复现了全部旧缺陷。

初实现运行仍失败两项导入：协议中 list 方法遮蔽注解 list，已通过延迟注解修正，[first.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/first.stderr.txt)。随后 16 项通过；扩展边界后 23 项通过。复核新增带引号未知版本断言，确实失败，再修复 codec：[quoted-version-before.stderr.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/quoted-version-before.stderr.txt)。所有中间失败保留，没有跳过或删除失败断言。

最终结果：

| 测试 | 结果 |
|---|---|
| G2a | 23 项，4.556 秒，OK，退出 0 |
| G1 | 14 项，0.041 秒，OK，退出 0 |
| G0 最终 | 15 项，10.935 秒，OK，退出 0 |
| git diff --check / 暂存检查 | 通过，无暂存改动 |

[最终 G2a 日志](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/final.stderr.txt)、[G1 日志](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/g1.stderr.txt)、[G0 日志](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/g0.stderr.txt)。

关键实测：
- 20 线程产生 20 个唯一文件；4 个 spawn 进程各 25 条共 100 条，ID/文件数正确。
- 两实例线程 CAS、两个 spawn 进程同 ETag CAS：仅一次成功，另一 CONFLICT；显式重新读取再 patch 保留两个字段。
- temp_opened、temp_written、file_fsynced、before_replace、replaced、dir_fsynced 各边界故障及终止进程；只见旧完整或新完整文件，临时垃圾不作笔记。
- 实际 fsync 失败、replace 失败、删除后目录 fsync 失败验证 IO_ERROR/COMMIT_UNCERTAIN；没有将真实锁/fsync/replace mock 成无操作。顺序测试 wrapper 实际调用系统接口，确认 file fsync→replace→directory fsync。
- 不参加 Repository 锁的读线程，在 40 次替换中只见完整 32 KiB A/B 正文。
- begin 在另一个进程持提交锁时不返回，释放后生效；新的进程写入仍 WRITES_PAUSED；错误格式恢复失败后继续暂停。
- 路径穿越、绝对 ID、反斜线、NUL、symlink/hardlink/目录、锁/控制文件符号链接被拒绝，临时外部保护文件不变。
- 独立子进程导入 storage，断言无 hello_agents/agent；未加载 LLM/Tracker。网络调用设失败 guard。

进程终止不等于真实断电。实测证明进程故障下完整可见性、系统同步调用顺序和失败语义；没有实际拔电或声称覆盖所有硬件/文件系统故障。

G0 本次独立构建目录为 venv/g0-zpcpynky，重新构建 wheel/sdist、空环境安装、pip check、storage 独立导入、Fake HTTP 与三种真实 Uvicorn 健康检查均通过。未修改依赖配置、未借用原 backend/.venv 的手工补包。证据：[g0-commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/g0-commands.json)、[g0-setup.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/g0-setup.json)、[g0-installed-environment.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/g0-installed-environment.json)、[g0-http-smoke.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/g0-http-smoke.json)，完整日志保存在 g2a_evidence/g0-logs/。构建仍有既存 license table 弃用提示，非失败。

## 8. 复跑命令

均在指定 WSL 仓库内执行。G2a/G1 使用 G0 验收过的独立运行环境，测试将当前 src 加入导入路径；笔记数据由 TemporaryDirectory 生成，不接触实际笔记。三个阶段分别运行以保留独立结果。

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G2_PY="$PWD/venv/g0-20261102-bd5dab4b/acceptance-final/runtime/bin/python"
"$G2_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_2a*.py' -v
"$G2_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_1*.py' -v

G0_BASE=/home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12
env -u G0_WORK_ROOT -u PYTHONPATH -u VIRTUAL_ENV \
  G0_BASE_PYTHON="$G0_BASE" G0_UV=/home/nhzj121/.local/bin/uv \
  "$G0_BASE" -B -m unittest discover -s tests/acceptance -p 'test_phase_0*.py' -v
~~~

精确 argv、cwd 和退出码：[final.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/final.json)、[g1.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/g1.json)、[g0.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g2a_evidence/g0.json)。

## 9. 回滚与 G2b 门槛

本阶段没有在线数据切换；代码回滚只需撤销新增模块/脚本与 G0 包内容断言扩展，保留 G0/G1 和原有用户修改。不要 git reset --hard 或清理未跟踪 docs。候选数据出错时停止使用候选目录，保留其内容用于检查；仅在合成演练中选择保护源作回滚，不把旧快照覆盖到新目录。

Repository、临时格式兼容、并发/故障/维护窗口验收与 G0/G1 回归均通过，没有发现阻碍 G2b 的 G2a 遗留问题。下一阶段仍需单独实现可信 ReadReceipt/GenerationBasis、项目 note 工具、Agent 组合适配、归属与幂等，并独立验收。现有 NoteTool 仍沿原路径运行，原工具的并发/路径风险并未因新增本包而自动消失。本阶段不做任何 Agent 集成或真实存储切换。
