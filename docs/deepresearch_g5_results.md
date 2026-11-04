# DeepResearch G5 依赖安全治理与发布验收

验收日期：2026-11-04；执行环境：WSL2 的 Ubuntu22.04.3，Linux 单机。依据当前工作区、既有审计/方案及 G0–G4a.2、storage activation 报告执行，没有采用旧审计版本号作为当前安全结论。

**结论：G5 依赖治理和规定的自动化验收通过，可交付内部稳定工程候选；尚不能宣称无条件完成对外正式发布。** 仍需关闭第 8 节的启动文档、正式部署配置和真实浏览器/代理链验收事项。本次没有实施 G4b/G6、访问真实笔记、修改正式 .env、调用收费服务、提交或推送。

## 1. 工作区基线与修改范围

Git HEAD 为 `2447fc91d41b3a46a7a4896d216355fad84abbfa`，分支 main。开始时已有 G4a.2 和 storage activation 的修改及未跟踪审计文件，全部保留；本次仅在其上进行 G5。完整初始状态及逐文件 SHA-256 见 [baseline.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/baseline.json)。

| 本阶段修改/新增 | 原因 |
|---|---|
| [frontend/package.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/frontend/package.json) | 移除无引用的 Axios；提高 Vue、Vite 的安全版本下界；对有证据的类型检查器依赖链升级 vue-tsc |
| [frontend/package-lock.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/frontend/package-lock.json) | 由 npm 正常解析生成兼容依赖树，固定版本、registry URL 和 integrity；lockfileVersion 保持 3 |
| [test_phase_5_release.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/tests/acceptance/test_phase_5_release.py) | 新增 6 项独立验收：manifest/lock/安装树、源副本一致及无 Axios、类型检查、生产构建、两组既有前端契约 |
| [本报告](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/deepresearch_g5_results.md) 与 [g5_evidence/](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence) | 保存联网审计、完整依赖/公告明细、命令、真实日志、回归及边界证据；包含保护旧证据的复跑控制脚本 |

已有后端源码、前端 src/tests、G2 安全实现、Python 依赖/锁、配置、README、忽略规则和历史报告/证据均未修改。两份 frontend 依赖文件以外的初始指纹全部一致，见 [scope-check.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/scope-check.json)。原 frontend/node_modules 与 dist 未覆盖；新安装和产物留在忽略的 `venv/g5-dwfu3mq5/`。因此原目录若仍有旧安装，启动前仍需按新锁文件重新安装，不能把本轮隔离安装当作已部署。

## 2. 依赖选择与兼容依据

### 2.1 直接依赖

下表的“安装版本”来自锁文件，而非 package.json 下界。

| 直接依赖 | 原声明 → 新声明 | 原安装 → 新安装 |
|---|---|---|
| axios | ^1.7.9 → 移除 | 1.12.2 → 移除 |
| vue | ^3.5.13 → ^3.5.44 | 3.5.22 → 3.5.44 |
| vite | ^6.0.7 → ^6.4.5 | 6.4.1 → 6.4.5 |
| vue-tsc | ^2.2.0 → ^3.3.14 | 2.2.12 → 3.3.14 |
| @types/node | ^22.10.5，未改 | 22.18.12 → 22.20.5 |
| @vitejs/plugin-vue | ^5.2.1，未改 | 5.2.4，未改 |
| typescript | ^5.7.3，未改 | 5.9.3，未改 |

对前端源码、测试、入口、配置等全文搜索，排除依赖声明/锁、安装/产物及 .env，没有 Axios 引用；实际请求使用 api.ts 的 fetch。移除后类型检查、构建和 HTTP/SSE 契约均通过。证据：[axios-reference-check.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/axios-reference-check.json)、G5 的源副本检查。

Vue 保持 3.x，Vite 保持 6.x，Rollup 保持 4.x，plugin-vue 5.2.4 的 Vite/Vue peer 范围继续匹配。查询时 [Vite 官方支持策略](https://vite.dev/releases) 仍将 6.4 列为安全修补分支。新公告明确 **6.4.4 本身**存在 deny 查询绕过，修复为 6.4.5，所以没有照抄旧方案的 6.4.4 下界。[维护者公告](https://github.com/vitejs/vite/security/advisories/GHSA-8g5g-mxqh-grgj)

vue-tsc 是唯一直接依赖主版本升级，原因可复核：

1. 先保留 2.x、完成其他兼容更新。最新 2.2.12 仍固定 @vue/language-core 2.2.12，其 minimatch 9.0.9 被当前 audit 的 `<11.0.1` 范围命中；3 个依赖节点共同追溯到 **1 条公告**。[同主版本审计](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/audit-same-major.json)
2. 未将 minimatch 9 强行覆盖成 11，也未使用 --force。registry 元数据表明 vue-tsc 3.3.14 → language-core 3.3.14 使用 picomatch，移除 minimatch/brace-expansion；TypeScript peer 仍为 >=5。[registry-candidates.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/registry-candidates.json)、[官方版本](https://github.com/vuejs/language-tools/releases/tag/v3.3.14)
3. 在实施副本中运行现有 TypeScript 5.9.3、SFC 类型检查、构建和真实 Vue setup/API 契约，全部通过，才复制 manifest/lock 回项目。没有为适配类型检查器修改源码或 tsconfig。

minimatch 的维护者公告主要描述 10.2.6、optimizationLevel>=2，而 npm 的受影响范围更宽。**本轮未复现本项目 minimatch 9 的可利用路径**；将此视为审计范围命中与维护风险，不能说已证实项目可被该路径攻击。升级移除依赖后审计解除。[原始公告](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249)

### 2.2 传递依赖与完整差异

按 lock 的 package 路径比较：83 个版本变化、29 个移除、10 个新增；其中 4 个直接依赖版本变化、1 个直接依赖移除，其余 117 项为传递节点变化。包含各平台可选包，不能把这些计数当成漏洞数量。[完整 122 项表](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/dependency-changes.md)、[机器可读差异](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/dependency-changes.json)

| 关键传递依赖 | 原版本 → 新版本/处理 |
|---|---|
| Rollup | 4.52.5 → 4.67.4；原生平台包同步更新 |
| Vue runtime/compiler/shared/server-renderer | 3.5.22 → 3.5.44 |
| @vue/language-core / @volar/typescript | 2.2.12 → 3.3.14 / 2.4.15 → 2.4.30 |
| picomatch | 4.0.3 → 4.0.7 |
| postcss | 8.5.6 → 8.5.32 |
| nanoid | 3.3.11 → 3.3.20 |
| source-map-js | 1.2.1 → 1.2.2 |
| esbuild | 0.25.11 → 0.25.12 |
| minimatch / brace-expansion | 9.0.5 / 2.0.2 → 移除 |
| follow-redirects / form-data | 1.15.11 / 4.0.4 → 随 Axios 移除 |
| alien-signals / entities | 1.0.13 → 3.2.1 / 4.5.0 → 7.0.1，由新父依赖声明正常解析 |
| @napi-rs/lzma-linux-x64-gnu | 新增 1.5.1，Rollup 的可选 Linux 原生依赖，属于构建工具链 |

没有手写传递依赖 overrides、修改包内部文件或引入额外业务库。新增 Volar/language-server 包来自 vue-tsc 的官方依赖树，实际 `npm ls --all` 无缺失或无效依赖。

## 3. 新审计结果及暴露面

联网查询使用 https://registry.npmjs.org；忽略用户 npmrc，不使用私有 registry 凭据。查询成功，不是 BLOCKED。原始 JSON、stderr 与退出码均保留。

| 检查 | 受影响依赖节点（高/中/低/严重） | 按 URL 去重的公告数 | 退出码 |
|---|---|---|---|
| 更新前全量 | 13（12/1/0/0） | 66 | 1，表示有命中 |
| 更新前 omit=dev | 8（7/1/0/0） | 43 | 1 |
| 同主版本候选 | 3（0/3/0/0） | 1 | 1 |
| 最终全量 lock 审计 | 0 | 0 | 0 |
| 最终 omit=dev lock 审计 | 0 | 0 | 0 |
| 最终已安装副本 npm audit，含/不含 dev | 均为 0 | 均为 0 | 均为 0 |

66 个公告标识中，npm 原始 via 严重性为高 31、中 33、低 2；与“13 个节点按传播后的最高严重性分类”含义不同。它们也不是 66 条已经复现的独立攻击路径。所有公告 ID、严重性和**各自完整受影响范围**见 [advisory-details.md](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/advisory-details.md)；数值和原始对象见 [audit-summary.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/audit-summary.json)。未将别名、父依赖传播或平台包计为额外独立漏洞。

按源包归组的原始公告数：Axios 32、Vite 9、brace-expansion 7、minimatch 4、PostCSS 4、nanoid 3、picomatch 2、@vue/server-renderer / follow-redirects / form-data / Rollup / source-map-js 各 1。全部命中节点已通过更新或移除解除；没有压制 audit、降低严重性阈值或忽略公告。

需要保留的判断边界：

- Vite 文件访问、WebSocket、launch-editor 等主要涉及开发服务器。最终静态站点不运行 Vite 服务，但构建机器及暴露的 dev server 曾有相应风险；不能因为它是 devDependency 就忽略。
- Rollup 的文件名遍历影响构建过程和不可信输入/插件，不是把 Rollup 直接打包到浏览器。npm 给出 high，维护者给出 Moderate，本报告保留差异；4.x 修补下界均指向 4.59.0。[维护者公告](https://github.com/rollup/rollup/security/advisories/GHSA-mw96-cpmx-2vgc)
- Vue SSR 公告在 registry 为 <3.5.42；维护者页面仍写受影响 <=3.5.41、Patched None。实际选用 3.5.44，本地 CR 属性名探针确实拒绝该输入，见 [探针](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/vue-ssr-cr-probe.stdout.json)，不能把陈旧字段解释成已验证所有变体安全。[原始公告](https://github.com/vuejs/core/security/advisories/GHSA-g2v6-rqmx-r4w6)
- Rollup 产物模块图显示实际浏览器 chunk 只包含 Vue shared/reactivity/runtime、应用及 Vite modulepreload 辅助；不含 SSR、Axios、Vite 服务端、Rollup、vue-tsc、PostCSS 或 minimatch。生产暴露面依据是 [实际模块图](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/production-modules.json)，而非简单使用 omit=dev 分类。Vue 的 compiler-sfc/PostCSS 可因 Vue 包依赖关系出现在 prod 审计图，但未进入此浏览器 bundle。
- 零已知 npm 公告是本次查询快照，不等于应用不存在漏洞，也不覆盖后端 Python CVE、供应链恶意包、认证/部署或模型输出风险。本阶段没有开展额外后端依赖升级或全面渗透测试。

官方链接的核查说明另存 [primary-sources.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/primary-sources.json)。

## 4. Node/npm、隔离安装与可重建性

实际使用 **Node v24.15.0 + npm 11.12.1（Linux x64/glibc）**，工具已存在，没有安装或切换用户全局环境。Vite 6 的包声明允许 Node ^18 / ^20 / >=22，但这不能当作新完整依赖树都支持 Node 18 的证明：Rollup 新增的可选 lzma 原生包要求 `^22.20 || ^24.12 || >=25`；npm 11.12.1 要求 `^20.17.0 || >=22.9.0`。本轮推荐直接复用已验证的 24.15.0/11.12.1，不承诺未测试的版本组合。[toolchain.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/toolchain.json)

隔离路径：

- 主验收副本：`/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/venv/g5-dwfu3mq5/candidate`。
- 第二次干净安装：`/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/venv/g5-dwfu3mq5/reproduce`，只复制最终 manifest/lock 后安装。
- npm 独立缓存：`/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/venv/g5-dwfu3mq5/npm-cache`。
- 新后端 G0 构建/运行环境：`/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/venv/g5-dwfu3mq5/backend-environment`。
- 生产产物：`/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/venv/g5-dwfu3mq5/candidate/dist`。

两次均实际执行 `npm ci --ignore-scripts --no-audit --no-fund`。采用方案要求的禁生命周期脚本模式；esbuild 所需平台可选二进制通过正常包安装获得，实际类型检查和构建验证可用，没有为通过测试放开额外安装脚本。审计独立联网执行，未通过 --no-audit 隐藏最终结果。

两个干净目录安装成功，`npm ls --all --json` 的完整 dependencies 树一致，第二次 ci 前后 manifest/lock SHA-256 不变。G5 用例还核对每个实际安装包与 lock 版本、所有锁定包的 integrity 以及未安装节点的 optional 属性。[reproducibility.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/reproducibility.json)、[ci-reproduce-command.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/ci-reproduce-command.json)、[tree-reproduce.stdout.txt](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/tree-reproduce.stdout.txt)

这证明当前 Linux 平台锁文件的干净安装复现；未声称跨所有 OS/CPU 或长期 registry 可用性已验证。

## 5. 实际测试及历史回归

### 5.1 结果

| 验收 | 实际结果 |
|---|---|
| 两次独立 npm ci | 均退出 0，实际安装 51 packages |
| Vue TypeScript 类型检查 | 退出 0；无源码/tsconfig 适配 |
| npm run build | 退出 0；包含 vue-tsc --noEmit，Vite 6.4.5，14 modules |
| G3 前端契约 | 17/17 通过 |
| G4a.2 前端契约 | 4/4 通过 |
| 新 G5 release 验收 | 6 tests，5.192 秒，OK |
| G0 | 15 tests，16.543 秒，OK |
| G1 | 14 tests，0.046 秒，OK |
| G2a | 23 tests，4.085 秒，OK |
| G2b | 29 tests，1.964 秒，OK |
| G3 后端 | 17 tests，0.433 秒，OK |
| G4a.1 | 25 tests，0.925 秒，OK |
| G4a.2 后端 | 27 tests，1.748 秒，OK |
| storage activation | 22 tests，12.197 秒，OK |
| 最终 lock/安装图全量及 prod audit | 均退出 0，零已知命中 |
| git diff --check / 暂存 | 通过 / 暂存为空 |

历史后端共 **172 tests**，加本阶段 6 项为 **178 tests**；前端契约 21 checks 单列，不重复计数。所有测试无跳过、无删除失败断言。本轮失败退出仅出现在治理前和同主版本候选的 audit 命中，均保留原始证据，不将它们伪称网络失败或成功。

构建输出：

~~~text
dist/index.html                  0.42 kB   gzip 0.31 kB
dist/assets/index-DVThMPvQ.css   21.32 kB   gzip 4.59 kB
dist/assets/index-DfDgyAxX.js    99.45 kB   gzip 38.85 kB
~~~

关键日志：[G5](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g5.stderr.txt)、[类型检查](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/typecheck-command.json)、[构建](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/build.stdout.txt)、[回归汇总](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/regression-results.json)、[G0](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g0.stderr.txt)、[G1](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g1.stderr.txt)、[G2a](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g2a.stderr.txt)、[G2b](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g2b.stderr.txt)、[G3](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g3.stderr.txt)、[G4a.1](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g4a_1.stderr.txt)、[G4a.2](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g4a_2.stderr.txt)、[接线](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/storage-activation.stderr.txt)。

### 5.2 真实入口、隔离与证据保护

G0 在全新环境构建 wheel/sdist、安装锁定运行依赖及 wheel、执行依赖检查、Fake HTTP 和三种 Uvicorn 启动形式。G1–storage activation 随后全部使用本轮新建的 G0 runtime，而不是 backend/.venv 或手工补包环境。完整构建/安装 argv 在 [g0-commands.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g0-commands.json)，版本在 [g0-installed-environment.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/g0-installed-environment.json)。

storage activation 重新走真实 Uvicorn 默认 Agent 工厂，使用 Fake 模型/搜索及临时空工作区；HTTP、SSE 各完成研究，真实创建任务笔记及 run_id + final_report 笔记，验证重启和无笔记安全降级，错误配置明确拒绝。[本轮实际启动样本](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/regenerated/storage_activation_evidence/actual-startup-workflow.json)

既有历史测试会重写其证据目录中的合成样本和启动日志。本轮控制脚本先保存字节，将新输出复制至 g5_evidence/regenerated/，再恢复旧证据。没有读写真实 notes 工作区；真实配置未被加载。恢复详情见 [history-preservation.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/history-preservation.json)。

在全部后端回归之后，又将**本轮**生成的 G3 和 G4a.2 样本送入新版依赖下的真实 api.ts / 编译 Vue setup 契约，共 21 项再次通过，然后恢复历史样本。[当前 G3 样本结果](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/frontend-current-g3.stdout.json)、[当前 G4a.2 样本结果](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/frontend-current-g4a2.stdout.json)。这是受控 fetch/ReadableStream 和编译后 setup 验证，不是浏览器 DOM 或公网代理链端到端证明。

### 5.3 可运行复跑命令

以下在指定 WSL 内运行。命令显式核对仓库，并仅在新的忽略目录中安装，不覆盖原 frontend/node_modules 或产物。

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source || exit 1
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G5_ROOT="$PWD"
G5_FRONT="$G5_ROOT/code/chapter14/helloagents-deepresearch/frontend"
G5_NODE=/home/nhzj121/.nvm/versions/node/v24.15.0/bin/node
export PATH="$(dirname "$G5_NODE"):$PATH"
export NPM_CONFIG_USERCONFIG=/dev/null
export NPM_CONFIG_REGISTRY=https://registry.npmjs.org
export NPM_CONFIG_FETCH_RETRIES=0
export NPM_CONFIG_FETCH_TIMEOUT=30000

G5_COPY="$(mktemp -d "$G5_ROOT/venv/g5-replay-front-XXXXXX")"
export NPM_CONFIG_CACHE="$G5_COPY/npm-cache"
cp "$G5_FRONT/package.json" "$G5_FRONT/package-lock.json"    "$G5_FRONT/index.html" "$G5_FRONT/vite.config.ts" "$G5_FRONT"/tsconfig*.json "$G5_COPY/"
cp -R "$G5_FRONT/src" "$G5_FRONT/tests" "$G5_COPY/"

(
  cd "$G5_COPY" || exit 1
  test "$(git rev-parse --show-toplevel)" = "$G5_ROOT" || exit 1
  npm ci --ignore-scripts --no-audit --no-fund &&
  "$G5_NODE" node_modules/vue-tsc/bin/vue-tsc.js --noEmit &&
  npm run build &&
  "$G5_NODE" tests/acceptance/phase3.mjs &&
  "$G5_NODE" tests/acceptance/phase4a2.mjs &&
  npm audit --json --package-lock-only &&
  npm audit --json --package-lock-only --omit=dev &&
  npm audit --json &&
  npm audit --json --omit=dev
) || exit 1

G5_PY="$G5_ROOT/venv/g5-dwfu3mq5/backend-environment/runtime/bin/python"
G5_FRONTEND_DIR="$G5_COPY" G5_NODE="$G5_NODE"   "$G5_PY" -B -m unittest discover -s tests/acceptance -p 'test_phase_5*.py' -v
~~~

全套后端回归使用本阶段控制脚本，保护历史证据，先构建新的独立环境再运行所有阶段：

~~~bash
cd /home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source || exit 1
test "$(git rev-parse --show-toplevel)" = "$PWD" || exit 1
G5_ROOT="$PWD"
G5_REPLAY="$(mktemp -d "$G5_ROOT/venv/g5-replay-back-XXXXXX")"
python3 -u -B docs/g5_evidence/run_backend_regressions.py   --work-root "$G5_REPLAY/environment"   --output "$G5_REPLAY/evidence"   --base-python /home/nhzj121/.local/share/uv/python/cpython-3.12.14-linux-x86_64-gnu/bin/python3.12   --uv /home/nhzj121/.local/bin/uv
~~~

本次实际后端精确 argv、cwd、耗时和退出码见各 `*-command.json`。控制脚本对任意非零退出或 skip 失败，不把缺少日志当成功。每次复跑应使用新目录；不存在的 G5_FRONTEND_DIR、缺失安装或与项目不一致的 manifest/lock 会使新增验收明确报错。联网 audit 若失败，必须解释为阻塞/失败，不能沿用本报告的零漏洞结果。

## 6. HTTP/SSE 与前端兼容性

本次仅变更依赖与验收材料，src 字节未改：

- HTTP 仍为 GET /healthz、POST /research、POST /research/stream，请求 topic/search_api 与原返回结构保留。
- SSE type、主要字段、task/note 状态分离、run_status/warnings、最终报告 run_id + final_report 归属均保留。
- G3 的 Planner 早到事件、仅 note_id 读取关联、错误 note_id 拒绝、异常 EOF、旧请求 event/catch/finally 隔离继续通过。
- G4a.2 的 ASGI 2.3 disconnect、2.4 OSError、服务端 deadline、后台容量保留、终态保护及 Abort 文案继续通过；取消仍不等于同步 provider 已终止或已经停止计费。
- ETag、ReadReceipt、GenerationBasis 及可信归属安全代码没有修改；全部 G2a/G2b 回归验证原约束仍然成立。

旧 UI 的使用方式、Vite 端口 5174、API base 配置没有改变。vue-tsc 仅改变开发/构建类型检查依赖，不新增模型调用、HTTP 字段或浏览器运行库。Vue patch 更新后未发现当前用例的行为差异，但没有将编译/Mock 测试冒充真实浏览器覆盖。

## 7. 发布检查（只读，未扩大修改范围）

检查事实及行号记录于 [release-checks.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/release-checks.json)。

| 检查 | 结果与证据 |
|---|---|
| 默认笔记策略 | [config.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/config.py:48) 默认 ENABLE_NOTES=true；[notes_runtime.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/services/notes_runtime.py:66) 要求 files_v2/激活目录；没有显式配置就拒绝。ENABLE_NOTES=false 安全降级仍正常，22 项接线测试包含真实启动验证 |
| 原 NoteTool 意外路径 | 项目后端 AST 中没有原 NoteTool 构造调用；[agent.py](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:14) 的兼容导入仍在，但 [构造检查](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/src/agent.py:51) 拒绝启用笔记却无 Repository。实际启动测试把旧构造器设为 forbidden，仍完成完整研究。未修改框架安装包，不声称第三方包中不存在该类 |
| README 是否一致 | 根 [README.md:83](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/README.md:83) 快速启动遗漏显式无笔记/激活步骤，直接照做会启动失败；[106 行](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/README.md:106) 的 5173 说明与项目 5174 不一致。backend README 的 [激活章节](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/code/chapter14/helloagents-deepresearch/backend/README.md:90) 准确，但前面旧启动片段需要结合该章节阅读。按任务要求仅报告，未代改 |
| 忽略规则 | venv、node_modules、dist、.env/.env.*、backend/notes、backend/notes-v2 及控制/标记/临时文件均匹配，见 [git check-ignore 结果](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/ignore-check.json)。任意自定义目录内的 Markdown 不能靠标记忽略规则自动覆盖；正式 workspace 推荐位于 checkout 外。没有创建这些探针路径或读取已有笔记 |
| HTTP/SSE | 路径、请求和事件保持；全套状态及取消回归通过 |
| G4b/G6 | 均未实施。本轮不引入上下文总预算、长时压测、新 Agent 能力或事件总线 |
| 浏览器/模型/代理 | 真实 DOM、真实反向代理断连链路、真实提供商行为与模型质量仍待部署验收；只完成规定的 Fake/Mock/ASGI/本地 Uvicorn 验证 |
| 敏感配置与正式数据 | 未修改正式 .env/凭据，未选择/初始化/迁移真实工作区，没有收费 API；回归数据均为 TemporaryDirectory 内的合成内容 |

## 8. 未解决风险与交付判断

**没有仍被本次 npm audit 命中的依赖风险。** 但以下事项不能据此自动关闭：

| 项目 | 状态/原因 | 发布前处理 |
|---|---|---|
| 根启动文档偏差 | 已确认，属于既有发布说明不一致；本任务规定只报告 | 下一次授权范围内统一 README 启动步骤与实际存储策略/端口 |
| 正式存储准入 | 未执行真实空新目录 init/check，符合数据保护范围 | 管理员核对保护源、在明确的新工作区验证激活；也可先显式 ENABLE_NOTES=false 发布无笔记模式 |
| 真实浏览器及部署链 | 尚未验收 DOM、实际 fetch Abort、代理缓冲、停服收尾 | 使用本次已构建产物在目标浏览器/代理完成启动、完整研究、取消及服务收尾验证；不能宣传立即停止模型/计费 |
| G4b 预算/压力边界 | 未实现总体输入/输出预算及长时压力验证；现有队列/同步请求边界仍在 | 对长研究、慢客户端、并发部署明确限制；若发布负载依赖这些能力，应先另行实施/验收 G4b |
| 多进程部署配额 | 准入是每服务进程，不是全机器配额 | 按进程数计算最大研究/Worker 与提供商预算；不把单机测试解释为全局限流 |
| 后端/部署安全 | 本阶段只治理 npm；未刷新 Python CVE 数据库，也未开展部署认证、安全头或全链路渗透审计 | 若对不可信网络开放，独立评审；现有开发用途配置不能由 npm 零漏洞证明适合公网 |
| 审计快照与工具链 | 公告/registry 会变化；当前只验证 Linux x64 与 Node 24.15.0/npm 11.12.1 | 发布时重跑 audit/ci，后续定期维护；不要把 package 的宽 engines 下界当作所有组合均验收 |

因此，**G5 自动化工程门满足，可作为已验收的内部稳定工程候选交付；对外正式发布仍有上述未闭环项，不给出无条件“生产就绪”结论。** 本轮不阻碍之后对剩余发布条件进行独立验收；不自动进入 G4b 或 G6。

## 9. 回滚与阶段停止

已保存本阶段之前的完整依赖对：[before-package.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/before-package.json)、[before-package-lock.json](/home/nhzj121/Agent/codex/projects/hello-agents/deep_search/hello-agents-source/docs/g5_evidence/before-package-lock.json)。回滚须成对恢复 manifest/lock，在另一个新的安装目录重新 ci/build/契约验证，并恢复此前前端制品；不要在活动 node_modules 中逐包降级，不要 reset/clean 整个工作区。

回滚会重新引入本报告的旧 npm 命中，须明确接受安全退化并重新评审开发服务器暴露；不能把回滚当作安全修复。后端、Repository、笔记及正式配置不属于 G5 回滚对象。原 node_modules/dist 本次未动，不需要任何数据迁移回滚。

本阶段完成后停止：没有提交、推送、迁移真实数据或提前实施后续阶段。
