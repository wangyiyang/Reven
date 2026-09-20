# Research: #127 公开内容、第三方许可与历史扫描设计

- Query: 如何以最小、可复查的改动移除第三方凭据并防止回灌，建立锁定依赖的许可证据，安排不会再次泄露秘密的历史扫描；Trellis 复制文件如何划分许可范围。
- Scope: mixed；仅研究设计和边界，不执行供应链全量审计。
- Date: 2026-09-21
- 工作目录：`/Users/wangyiyang/Documents/Github/worktrees/Reven/codex/gh-127-open-source-alpha`。
- 用户决策：Reven 原创代码采用 Apache-2.0，原创版权主体 Wang Yiyang；不表示第三方代码也可改用该许可证。

## Findings

### 1. 结论与实施边界

1. 可以保持“原创应用 Apache-2.0”的方向，但不能宣称全仓文件统一 Apache-2.0。除 Doocs 之外，仓库还复制了 Trellis 0.6.15 的脚本、钩子和技能；该版本上游采用 AGPL，须独立保留其许可与来源。
2. 删除当前 Token 文件不够：同步脚本会复制整个 shared 目录，必须在暂存区清理文件及 barrel export，再验证并原子替换；已有 vendor 测试要主动重新注入无效夹具，证明下一次同步仍不会带回文件。
3. 许可核对必须区分源码仓库、打包后的 JS/字体、Python/Ruby 运行时、镜像系统组件。现有 SBOM 步骤指定的是漏洞扫描，不能当作全部许可证及声明交付已完成。
4. 历史审计应在独立完整镜像副本进行，先记录可见 refs 和工具版本，再脱敏扫描、逐项分类；公开报告只保留定位及处理结果。删除当前文件不能清除旧提交。

### 2. Files found 与代码模式

| 文件与行号 | 用途 / 已确认事实 |
| --- | --- |
| `vendor/doocs-md/shared/src/configs/api.ts:1`、`:24` | 两组 GitHub/Gitee API 配置声明；本研究不记录任何值，不验证凭据 |
| `vendor/doocs-md/shared/src/configs/index.ts:2` | 将 `./api` 重导出 |
| `vendor/doocs-md/shared/src/index.ts:2` | shared 根入口继续重导出 configs |
| `vendor/doocs-md/shared/package.json:9` | 暴露 configs 子路径与通配子路径；删除文件后也应检查其他直接引用 |
| `scripts/vendor_doocs.sh:4`、`:5` | 固定上游仓库及提交 `c37c1d6cc0e0a259de20305b9e4c3b59c7029da7` |
| `scripts/vendor_doocs.sh:109` | 生成 UPSTREAM.md；清理规则应写在这里，避免人工记录被覆盖 |
| `scripts/vendor_doocs.sh:127` | 暂存区校验入口；可以加入“禁用 API 配置文件不存在、导出不存在”的断言 |
| `scripts/vendor_doocs.sh:158`、`:163` | 全量复制 upstream shared 后验证；局部净化应放在复制后、校验前 |
| `scripts/vendor_doocs.sh:166` | 现有备份、替换、失败恢复流程，无须为此任务重构 |
| `scripts/test_vendor_doocs.sh:11`、`:12` | 测试上游直接由当前 vendor 树复制；删文件后若不主动插入夹具，会失去回灌场景 |
| `scripts/test_vendor_doocs.sh:76`、`:93` | 现有故障恢复与重复执行一致性测试可复用 |
| `renderer/src/render.ts:3` | renderer 直接使用 theme，不依赖 GitHub/Gitee 配置 |
| `vendor/doocs-md/packages/core/src/theme/themeApplicator.ts:8` | 上游 core 仍使用 configs barrel，清理 barrel 必须维持其他导出 |
| `vendor/doocs-md/UPSTREAM.md:3`、`:6` | 固定版本、来源、WTFPL v2 已记录 |
| `vendor/doocs-md/LICENSE:4` | 已保留 Doocs 的原始版权行 |
| `vendor/doocs-md/patches/juice@11.1.1.patch:5` | 分发了对 Juice 的修改，不能把其上游包许可归入 Doocs 许可一并代替 |
| `package.json:4`、`:14` | pnpm 固定 10.13.1，Juice 固定补丁 |
| `pnpm-workspace.yaml:1` | web、renderer、3 个 Doocs 包组成 JS workspace |
| `web/src/index.css:1` | 实际导入 Inter、JetBrains Mono、Noto Sans SC 字体资源 |
| `pnpm-lock.yaml:765`、`:768`、`:771` | 3 个 Fontsource 包均锁定 5.3.0 |
| `uv.lock:514`、`:526` | `deepseek-harness-runtime-bin` 与 SDK 均为 0.1.5rc1；包含原生运行时，不能只看 Python 包名 |
| `server/pyproject.toml:5` | 后端直接运行依赖定义 |
| `infra/blog/runtime/Gemfile:3` | Ruby 直接依赖 faraday-retry、github-pages、webrick |
| `infra/blog/runtime/Gemfile.lock:281`、`:293` | 多平台 gem 解析及 Bundler 2.5.22 锁定信息 |
| `infra/docker/Dockerfile:2`、`:21`、`:28` | Node、uv/Python 构建阶段、Python runtime 均以 digest 固定 |
| `infra/docker/Dockerfile:30` | apt 系统包没有逐项固定版本，需对实际构建镜像记录版本 |
| `infra/docker/Dockerfile:36`、`:49`、`:51` | 分发 Ruby bundle、Python .venv、单独复制的 Node executable |
| `infra/docker/Dockerfile:52`、`:53` | 最终镜像只复制打包后的 renderer、web 静态资源，没有 JS node_modules |
| `.github/workflows/ci.yml:249`、`release.yml:79` | Trivy 0.64.1 生成 CycloneDX，参数为 `--scanners vuln` |
| `.trellis/.version:1` | 当前开发工具模板版本为 0.6.15 |
| `.trellis/.template-hashes.json:111`、`:157`、`:159`、`:215`、`:216` | 记录技能、代理、钩子、脚本、workflow 的上游管理痕迹；共 213 个模板路径 |
| `.agents/skills/trellis-meta/references/local-architecture/generated-files.md:23` | 区分工具模板与项目维护的 spec、task、workspace 材料 |

引用行号以本次读取时的 worktree 为准；主代理并行更新的 PRD 不作为稳定代码定位。

### 3. Token 文件最小净化方案

**已确认：**对 renderer、web、vendor core/shared 的静态查找没有发现 `githubConfig`、`giteeConfig` 的消费者；configs barrel 确实导出该文件。`tokenTools.ts` 是编码辅助函数，本次没有证据要求一并删除，避免按名称扩大清理。

**建议实现：**

1. 删除当前 `vendor/doocs-md/shared/src/configs/api.ts`，只删除 configs/index.ts 对它的重导出。
2. 在 `vendor_doocs.sh` 添加短小净化函数，作用对象仅为复制完成的 staging shared：移除同一 API 文件并精确删除相应 export。放在 `:161` 后、`validate_staging` 前。
3. `validate_staging` 加入文件和 export 均不存在的断言；若出现新的消费者，使构建显式失败，不保留空的伪配置或注入替代 Token。
4. `write_upstream_metadata` 与当前 UPSTREAM.md 同步记录：Reven 有意排除不用于渲染的托管服务配置、修改 barrel；保留上游 LICENSE 和固定提交。
5. 测试在伪上游主动写入**明确无效、不会匹配真实服务格式**的配置夹具及 export；同步后检查两者被清除，并继续执行既有故障恢复、重复同步一致性断言。不能仅从已经净化的 vendor 树复制测试上游后检查不存在。
6. 验证 renderer 的实际 build/test；这既覆盖 barrel 变动的解析，也避免仅用文本检查代替行为验证。完整扫描再检查仓库其他位置与历史，禁止全局忽略 vendor。

### 4. Trellis 许可边界：已确认与待核对

**已确认：**

- 固定 tag `v0.6.15` 的上游 LICENSE 是 GNU AGPL v3。[固定版本许可](https://raw.githubusercontent.com/mindfold-ai/Trellis/v0.6.15/LICENSE)
- COPYRIGHT 保留 Mindfold LLC、2026，含 v3 或后续版本表述；同版 npm CLI manifest 的 `license` 为 `AGPL-3.0-only`。两者表述不完全一致，实施时原样保留文本并记下差异，不能自行宣称获得 Apache 授权。[COPYRIGHT](https://raw.githubusercontent.com/mindfold-ai/Trellis/v0.6.15/COPYRIGHT)、[CLI manifest](https://raw.githubusercontent.com/mindfold-ai/Trellis/v0.6.15/packages/cli/package.json)
- 读取该版本完整上游文件树，名称含 license/copyright/exception 的文件只有根 LICENSE、COPYRIGHT；检查 README 和上述文件未发现模板例外。此结论是“查阅范围内未发现”，不等于证明不存在单独协议。
- 将两个本地文件与固定版本上游模板在内存中比较，均逐字节一致：`.trellis/scripts/task.py` 对应 `packages/cli/src/templates/trellis/scripts/task.py`；`.codex/hooks/inject-subagent-context.py` 对应 `packages/cli/src/templates/shared-hooks/inject-subagent-context.py`。因此这里存在实际源代码复制，并非只有一次工具执行产生的原创输出。[task 模板](https://raw.githubusercontent.com/mindfold-ai/Trellis/v0.6.15/packages/cli/src/templates/trellis/scripts/task.py)、[hook 模板](https://raw.githubusercontent.com/mindfold-ai/Trellis/v0.6.15/packages/cli/src/templates/shared-hooks/inject-subagent-context.py)
- `.trellis/.template-hashes.json` 可作为路径清单起点；覆盖不止 `.trellis/`，还包括 `.agents`、`.claude`、`.cursor`、`.codex`、`.dsh` 的受管理文件。必须逐项确认实际存在和修改状态；文件 hash 是出处线索，不是授权文件。
- 当前 Dockerfile 使用定向 COPY：应用源码、编译产物、依赖环境、infra。没有 COPY `.trellis` 或平台工具目录，也没有 `COPY . .`；在 `server/src`、`web/src`、`renderer/src`、`infra` 查找没有发现 Trellis 运行引用。因此已知镜像路径没有包含这些开发工具。

**最小设计：**根许可证与 README 明确“Reven 原创应用代码 Apache-2.0；第三方代码与工具按各自许可”。为确认复制的 Trellis 文件保留独立 LICENSE/COPYRIGHT、版本与上游链接、受影响路径清单、已有本地修改说明。不要把整个 `.trellis/` 一刀切成第三方文件：任务研究、项目规格和工作日志含项目自己的材料；应以受管理模板、来源比较和人工复核区分。

**不能作出的推断：**仅因开发工具采用 AGPL，不能推断 Reven 应用整体必须 AGPL。上游 AGPL 本身区分单独作品聚合与组合派生作品；这里的技术边界证据支持独立记录工具，但不替代对个别复制/修改文件的许可核对。若后来发现把 Trellis 源码复制进应用模块，须单独重查这一边界。

**公开材料边界：**发现 26 个 task.json 及任务/工作区记录；这里只确认其存在与用途，未逐篇审计。Git 公开会同时公开版本库中这些材料及历史；凭据扫描之外，仍需人工检查内部地址、账号标识、私人信息、对话引用及无需公开的经营资料。不得把全部 task/workspace 文档套用工具模板的版权结论。

### 5. 最小可复查许可清单

无需先建设完整合规平台。建议交付一份路径/组件清单、一份必要许可文本集合、一份按版本记录的例外处理表，以及可重跑的采集命令。至少记录：`scope / name / exact version or commit / source / license expression / evidence path+SHA256 / shipped artifact / required notice or source action / review status`。状态分“已确认”“待核对”“不随本分发物交付”，不得把 UNKNOWN 自动变成 MIT。

| 范围 | 最小采集方法 | 复查边界 |
| --- | --- | --- |
| JS 锁定依赖 | 在干净 Linux AMD64 构建环境使用 pnpm 10.13.1，`pnpm install --frozen-lockfile` 后 `pnpm licenses list --json --long`；为 5 个 workspace 明确验证覆盖，不只扫根包 | 完整 inventory 留出 dev/prod 标识；以锁文件的所有名称+版本校验平台可选包遗漏，未安装项标记原因；收集实际安装包 LICENSE/NOTICE，不能只看 registry 的 license 字符串 |
| Python | 依照 Dockerfile `uv sync --frozen --no-dev --all-packages` 的 Linux 环境，通过标准库 `importlib.metadata.distributions()` 读取 Name/Version、License-Expression、License、Classifier、License-File 及对应文件 | uv.lock 112 条 package 包含工作区/开发/平台范围；与实际 runtime 集合区分；轮子可含本机库/二进制，特别复核 deepseek-harness-runtime-bin、cryptography 等二进制分发所带许可，不假定 SDK 许可覆盖所有嵌入组件 |
| Ruby | 在最终 Linux 构建环境使用 Gemfile.lock 与 Bundler 2.5.22；`BUNDLE_GEMFILE=/opt/reven-blog/Gemfile bundle exec ruby` 读取 `Bundler.load.specs` 的 name/version/platform/licenses/full_gem_path，收集 gems 内 LICENSE/COPYING/NOTICE | 不用开发机全局 gem list 冒充 bundle；github-pages 引入大量插件、主题、native gems，不能仅列 3 个直接依赖 |
| 字体 | 对锁定 5.3.0 的 3 个 Fontsource 包检查实际包内许可与原始版权，记录随 web build 输出的字体文件 | Repo 无独立字体文件不代表产品未分发字体；若实际包确认 OFL，保留版权与 OFL 原文，遵守其字体名称和再分发要求；本次未下载字体包，尚不把其具体声明认定已核验 |
| 镜像 | 保留现有 CycloneDX，另对**最终镜像 digest**执行 `trivy image --scanners license --license-full --format json`，记录 Linux/AMD64、base digest、实际 dpkg/gem/Python 包版本及许可出处 | `apt-get` 无版本固定，报告只适用于该构建 digest；镜像含 Git、Ruby、bubblewrap、tini、编译工具等，逐项分清声明与对应源码义务；不能仅放一个上游网址便声称所有义务已履行 |
| 独立服务镜像 | 记录 Compose 的 Caddy digest，以及新增 PostgreSQL 的确切来源/版本 | 用户自己从上游拉取，与项目重新托管/再分发这些镜像的责任边界不同；发行文档说明谁提供镜像 |
| vendored / 工具 | Doocs 固定提交 + patch；Trellis 模板固定版本 + 复制路径 | 这两类不会由 npm/Python runtime 的清单完整发现，须手工补入 |

`pnpm licenses` 官方定义是“已安装包”的许可枚举，所以不能仅输出一份 JSON 就宣布锁文件所有可选平台版本均审完。[pnpm 10.x 文档](https://pnpm.io/10.x/cli/licenses) Python 的新旧元数据共存，需要优先读取 License-Expression，再保留旧 License/Classifier 和 License-File 的证据。[PyPA metadata](https://packaging.python.org/en/latest/specifications/core-metadata/#license-expression) Ruby 的 licenses 是 gemspec 元数据，仍需与文件原文核对。[RubyGems specification](https://guides.rubygems.org/specification-reference/#licenses)

**当前打包缺口需要落实到文件：**

- Dockerfile 只复制 Node executable，没有复制 Node 随附的许可证/第三方声明；Doocs 根 LICENSE 也不在当前 COPY 路径中。最终产物必须有可定位的第三方声明目录。
- renderer 使用 `ssr.noExternal: true`（`renderer/vite.config.ts:25`），web 也生成静态 bundle。容器中缺少 node_modules，扫描器无法保证从压缩 JS 还原全部依赖；须在构建阶段生成/收集 JS 许可证据，并随产物复制。
- 字体分发声明必须随 web/镜像交付；在 Git 根放 LICENSE 不会自动出现在浏览器收到的字体资源旁或镜像内。
- 原创 Apache 文本、必要 NOTICE、第三方许可文本应统一有明确打包位置；不要为了形式生成不必要的 NOTICE，也不要遗漏依赖原有 NOTICE。[Apache-2.0 第 4 条](https://www.apache.org/licenses/LICENSE-2.0)
- `infra/docker/Dockerfile.dockerignore:15` 排除了 docs；若把许可集合放在 docs 下，后续 COPY 会失败或缺失，实施时应选定不会被忽略的目录并写镜像验证。
- Trivy 的 `--scanners license` 与 `--license-full` 是专门许可功能；结果是线索和分类，不是兼容性自动裁决。[Trivy 0.64 许可扫描](https://trivy.dev/docs/v0.64/scanner/license/)

### 6. 全历史扫描：命令与不泄露报告策略

以下均为**给实施阶段的建议命令，本研究未执行 Git、扫描器或任何历史改写**。

**范围与准备：**使用独立、权限受控的完整 mirror；通过已有安全认证获取拟公开远端所有分支和 tag，不把凭据放 URL/命令行。检查不是 shallow repository，保存所获取 refs+SHA、扫描时间、工具版本/二进制校验和、规则配置 hash、退出状态。工作树在另一轮扫描；不要直接 `gitleaks dir .` 扫整个开发目录，因为这会读到真实 .env、缓存、local runtime。用已确认拟公开的受版本控制文件快照作目录扫描对象。

建议由主会话在授权范围内执行：

```bash
umask 077
audit_dir="$(mktemp -d /tmp/reven-disclosure-audit.XXXXXX)"
audit_repo="$audit_dir/repository.git"
git clone --mirror git@github.com:wangyiyang/Reven.git "$audit_repo"
git --git-dir="$audit_repo" rev-parse --is-shallow-repository > "$audit_dir/shallow.txt"
git --git-dir="$audit_repo" for-each-ref --format='%(refname) %(objectname)' > "$audit_dir/refs.txt"
gitleaks version > "$audit_dir/scanner-version.txt"
scan_status=0
gitleaks git "$audit_repo" \
  --log-opts="--all --full-history -m" \
  --redact=100 --no-banner --log-level=error \
  --exit-code=13 --report-format=json \
  --report-path="$audit_dir/findings.private.json" \
  > "$audit_dir/scanner.private.log" 2>&1 || scan_status=$?
printf '%s\n' "$scan_status" > "$audit_dir/scanner-status.txt"
```

- 实施时先固定 Gitleaks 版本及校验和，并检查该版本帮助；不使用浮动 `latest`。官方当前接口为 `git`/`dir`，支持 `--log-opts`、`--redact`、自定义 exit code。[Gitleaks 官方说明](https://github.com/gitleaks/gitleaks#usage)
- 把 0、13、其他状态分别当作“无检测项”“检测到条目”“扫描执行异常”；不能将检测项或错误吞成成功。记录报告是否成功产生、扫描范围是否完整，失败不能标为通过。
- `--redact=100` 是第一层保护，日志与 JSON 仍一律按敏感材料保存在临时目录，不直接上传、提交、粘贴。公开前另生成白名单字段：`RuleID, File, StartLine, EndLine, Commit, Fingerprint`；再补 `classification, resolution, reviewer, date`。删除 Match、Secret、代码片段、提交信息、作者邮件、原始日志等字段。公开文件名和上下文也需人工复核。
- 首次完整审计不要使用历史 baseline、禁用通用规则或整目录 allowlist 来消除告警。确认固定测试占位值后才对具体规则/路径/无效值写最小例外及原因；例外回归测试须证明同路径新增真实格式凭据仍被检测。
- 扫描结果只说明检测规则命中的信息；应追加人工复核旧文档、任务与工作日志、个人环境标识，覆盖非密钥型敏感数据。除代码 refs 外，Issue/PR 评论、Release 附件、Actions 日志、Git LFS 内容、GitHub 缓存/隐藏 refs 不包含在普通 mirror 的完整性声明中，须另列核对范围。
- 当前 API 文件的上游来源不等于其 Token 可公开。按未知状态处理，联系归属方/轮换的实际操作由授权的维护者执行，不调用 API 验证有效性。
- 如确认真实秘密，先撤销/轮换并确定实际暴露范围，再单独规划历史改写、受影响 refs、fork/clone/缓存处理。GitHub 说明历史重写存在副作用且不能清除别人已有副本；不要把本次源码清理提交或本地扫描通过当作全网清除证据。[GitHub 敏感历史清理说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

### 7. Related specs 与验证建议

- 已读 `.trellis/workflow.md`：本阶段留在研究/设计，成果写研究文件，不开始产品改动。
- `.trellis/spec/reven-server/backend/ci-release-contract.md:18`：容器全量检查仍受 `inputs.full` 控制；为许可/扫描增加门槛时不能无意恢复日常 PR 的容器构建。
- `.trellis/spec/shared/frontend/index.md`、`core/frontend/index.md`、`renderer/frontend/index.md` 当前多为占位指引，没有现成 vendoring 许可或公开历史契约。
- 实施验收的最小独立证据：vendor 伪上游回灌测试通过；renderer 构建/测试通过；生成许可集合后镜像内存在必要文本且与实际分发版本对应；扫描报告有 refs、版本、状态及逐项处理结论；未处理的许可/凭据项目不得标为 AC1/AC2 完成。

## Caveats / Not Found

- 此文件只写研究设计；没有读取真实 .env，没有请求凭据验证，没有执行 Git 命令，没有改代码、规范、脚本或平台配置。
- 本工作树未安装 node_modules/.venv；未下载所有依赖包、未构建镜像，因此没有声称锁定供应链已审完，也没有为具体字体和原生运行时做最终许可结论。
- 本机 `python3` 缺少 `tomllib`，改用只读文本/JSON提取事实；没有为研究安装依赖。正式 Python 元数据采集应使用项目 Python 3.12 环境。
- Trellis 固定版本许可证、COPYRIGHT 与两个模板复制样本已核验；其余 213 条模板路径尚未逐一比较，未找到模板授权例外。源码聚合与组合派生关系应按实际引用判断，不能从工具许可推断整个产品许可。
- 当前无项目级 LICENSE/NOTICE，只有 Doocs LICENSE；新增原创许可仍须显式排除/说明第三方各自的许可范围。
- Gitleaks 方案是建议，不是已完成的“完整 Git 历史扫描”。任何公开/改写/轮换都需由主会话按实际授权执行。
