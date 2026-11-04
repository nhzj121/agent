# 开发环境与协作约定

## 唯一项目位置

- WSL 发行版：`Ubuntu22.04.3`（WSL2）。
- Linux 项目根目录：`/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source`。
- Windows 访问路径：`\\wsl.localhost\Ubuntu22.04.3\home\nhzj121\Agent\codex\projects\hello-agents\deep_search\hello-agents-source`。
- Git 远程仓库：`https://github.com/nhzj121/agent.git`。
- Windows 目录 `E:\Deck_all_need\projects\work\agent` 仅用于承载入口说明，不是项目代码开发目录。维护此处的指令文件不属于项目代码修改。

## 执行要求

- 每次处理项目相关问题或任务前，先确认上述环境约定；开始操作时，实际核对 WSL 发行版、当前目录和 Git 仓库根目录。
- 项目文件的读取和修改、依赖安装、运行、测试及本地 Git 操作必须在上述 WSL 环境内执行，使用 Linux 工具链。
- 若会话仍运行在 Windows，通过 `wsl.exe -d Ubuntu22.04.3` 调用 Linux 工具，并显式定位上述 Linux 项目根目录。
- 每条修改、安装、运行、测试或本地 Git 命令都必须先成功定位项目目录，并核对 `git rev-parse --show-toplevel` 与上述根目录一致；定位或核对失败立即停止。
- 不依赖上一次命令保留的工作目录。不得回退到 Windows 目录执行项目任务，也不得在 Windows 目录创建替代开发副本。
- 修改具体文件前，读取该文件所在目录适用的更细层级指令。
- WSL 访问或写入权限不足时，明确报告阻碍并按环境要求处理权限，不得改用 Windows 副本继续。

## Git 边界

- 本地 Git 操作使用目标 WSL 仓库内的 Linux Git。
- 所有推送相关操作由用户本人执行；不得执行 `git push`。
- 不得通过 GitHub 插件、API 或其他方式直接修改远程仓库，以替代用户推送。

## 沟通与需求

- 实现具体要求前，先明确影响实现的疑点和缺失资料，并向用户询问；不得以猜测代替关键需求。
- 已经确认的事项无需重复询问；没有新的疑点时，按已确认要求执行。
- 直接指出问题和建议，避免不必要的肯定。可从科学、理性角度质疑方案，除非用户明确要求采用。
- 解释方案时，直接说明用途和原因，重点考虑适配度、可行性、准确性及安全性，并在有实际取舍时提供可选方案。
- 必要时追查相关逻辑和根因，不局限于表面现象。
