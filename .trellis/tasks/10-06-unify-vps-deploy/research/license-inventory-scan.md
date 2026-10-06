# Research: 许可清单原始 manifest 导致 tinypool 镜像扫描阻塞

- Query: tinypool 1.1.1 的 CRITICAL 告警是否来自运行程序；能否在不升级依赖、不修改 manifest/锁文件、不降低门禁的范围内修复部署包装。
- Scope: mixed；本代理只读仓库与本地已安装包，CI/SBOM 证据由主会话独立核实并提供；仅写本研究文件。
- Date: 2026-10-06
- Repository: /Users/wangyiyang/.codex/worktrees/unify-vps-deploy/Reven
- CI evidence: [full CI run 37406608589 / container 112085508698](https://github.com/wangyiyang/Reven/actions/runs/37406608589/job/112085508698)

## Findings

### 结论与证据分层

这次扫描识别出的两个 tinypool component 都由**许可目录的原始 package.json** 建立，不能据此判定最终镜像安装了 tinypool 的可执行包。可在用户“不升级依赖”的范围内修复包装：停止输出这些原始包 manifest，完整保留 LICENSE/版权/NOTICE、真实名称版本来源及原 manifest SHA-256；不简单改名、不按包名/CVE 删除、不改变扫描门禁。

这项修改不会修复构建工具漏洞：构建阶段仍按 frozen lock 安装原 Vitest/tinypool。最终是否解除镜像扫描阻塞，必须由重新构建后的同一 Trivy CRITICAL 门禁证明。

主会话已经核实以下 CI/SBOM 事实；本代理不重复下载或审查 advisories：

- 真实隔离 smoke 的 HTTP/认证/TLS/生产网关成功标记已核实。
- CRITICAL gate 随后因 tinypool 1.1.1 的 CVE-2026-104848 / CVE-2026-104849 失败，修复版本分别为 2.1.1 / 2.1.2。
- SBOM 的两个 component 唯一列出的路径：
  - `opt/reven-licenses/javascript/packages/tinypool@1.1.1/package.json`
  - `app/web-dist/licenses/javascript/packages/tinypool@1.1.1/package.json`
- SBOM 没有为这两个 component 列出程序路径；这不是对镜像所有原生/压缩载荷的完整源码审计。

### Files found / 可复核代码路径

| 文件与行号 | 事实 |
| --- | --- |
| `web/package.json:30-50` | Vitest 声明为 devDependency；不是 web 运行依赖。 |
| `pnpm-lock.yaml:2133-2135,4389-4409` | Vitest 3.2.7 依赖 tinypool 1.1.1，版本/完整性由锁文件固定。 |
| `scripts/licenses/collect-js.mjs:19-35` | 遍历当前已安装 workspace dependency graph，含 dependencies/devDependencies/optionalDependencies。 |
| `scripts/licenses/collect-js.mjs:6-16,38-57` | 复制许可/版权/NOTICE 类原文；第 50 行另输出原始 package.json，并在 inventory 保留名称/版本/许可/来源/证据。 |
| `scripts/licenses/collect-js.mjs:60-80,97-104` | 补充原文按名称版本匹配并校验 SHA-256；inventory 保留 lockfile SHA-256，明确超集不是 bundle reachability。 |
| `infra/docker/Dockerfile:2-15` | Node build 先 frozen 安装和 build，再采集许可；把整个许可目录复制进 web/dist/licenses/javascript。 |
| `infra/docker/Dockerfile:24-44` | 最终镜像从 Node stage 只复制 JS 许可目录及 web/dist，不复制 Node stage 的 node_modules；两处原 manifest 来源因此闭合。 |
| `infra/docker/Dockerfile.dockerignore:9-13` | 本机 .venv、node_modules、dist 不进入构建上下文；镜像使用 build stage 自己的锁定安装和产物。 |
| `scripts/licenses/test_collectors.py:50-92` | 可复用的假依赖树测试验证嵌套 NOTICE 保留、UNKNOWN/缺原文提示、残留退役包排除；不需安装第三方库。 |
| `THIRD_PARTY_NOTICES.md:20-35` | 项目分发契约要求许可全文/版权/NOTICE、名称版本、来源及哈希；清单含 dev 工具，不宣称每个包进入 browser bundle。 |
| `licenses/REVIEW.md:9-12,21-34,54-59` | 字体完整许可、版本匹配与校验、未解决原文/内嵌组件审查不能因本修复而删除。 |
| `.github/workflows/ci.yml:232-245` | Trivy 0.64.1 固定镜像，生成 CycloneDX 后 `--exit-code 1 --ignore-unfixed --severity CRITICAL`；必须保持。 |
| `.github/workflows/release.yml:85-108` | 正式镜像仍有 CRITICAL gate 与 SBOM；不能只让 CI 通过而降低正式发布门禁。 |

### 本地已安装包的证据

`node_modules/.pnpm/tinypool@1.1.1/node_modules/tinypool/package.json:21-30` 的 exports/main/module 指向 `dist/index.js`。真实程序文件存在于该包 `dist/`，包括 `index.js`、worker/process entry 与 utils。

对该包运行许可采集的现有选择规则，只会保留包根 LICENSE，以及额外附加的 package.json；不会复制 dist 程序。该包 LICENSE 第 3-16 行包含原始版权、许可条件及归属说明，须完整保留。

本地只读 SHA-256 核查：

| 源文件 | SHA-256 |
| --- | --- |
| tinypool@1.1.1/package.json | `fab0aa2756e7cf5c2dc020daafa86c2b5fa3cfd2f9087393418b9a7379dc3dda` |
| tinypool@1.1.1/LICENSE | `0d506ca1b2adc4ee63a9e2384a85d6cf9f014b4cf3d00c162cd60216450324fa` |

本地 `web/dist/assets/index-*.js` 未命中 tinypool/worker_threads 字符串，应用入口 `web/src/main.tsx:1-20` 未导入测试工具；但字符串未命中不能证明所有 bundle 可达性。另 `web/vite.config.ts:4` 仍在构建配置中导入 vitest/config，不能将构建风险描述为已移除。

### 最小包装修复建议

1. **只调整许可采集输出。** 删除 collectPackage 输出 `packages/<id>/package.json` 的步骤；仍读取原 manifest，用它生成现有 inventory 的名称/真实版本/license/source。
2. 在该包 inventory 记录新增原 manifest SHA-256 来源证据，例如 `package_manifest_sha256`；哈希从原始读取 bytes 计算，不修改或规范化版本信息。名称/版本/来源和 hash 继续可追溯，**不再分发包含 main/exports/scripts 等运行描述的完整包 manifest**。
3. 保留所有包的 LICENSE/COPYING/COPYRIGHT/NOTICE/AUTHORS/OFL 原文、嵌套路径、既有 evidence hashes、supplemental 原文及 checksum 门禁；inventory 的 dev 工具超集与 review/UNKNOWN 标记保持。
4. 不按 tinypool 或 CVE 过滤 inventory；不改 raw manifest 的文件名来隐藏同一内容；不删除有真实程序载荷的元数据；不修改 .trivyignore、skip-dirs/skip-files/ignore policies/scan severity。
5. 仓库的 package.json、web/package.json、pnpm-lock.yaml、Python manifests 和 uv.lock 保持；无需 dependency override 或 pnpm update。Dockerfile 两处 COPY 自然取得新的许可输出，通常无需修改 COPY 结构。
6. 更新许可采集回归：嵌套原文 bytes/hash 完整不变；package identity/version/source 不变；原 manifest hash 等于 fixture 原始 bytes SHA-256；许可输出树没有原始 package.json；MISSING/UNKNOWN 和补充原文校验仍正常。
7. 如仅改 collector，日常 CI 的 paths filters 当前未包含 `scripts/licenses/**`；此次至少显式执行回归并跑 full CI，不把 skipped job 当通过。如要补过滤，应作为部署包装验证的最小相关改动，继续保持 container full-only。

### 可验证的验收步骤（建议，未执行）

- 执行 `python3 -m unittest discover -s scripts/licenses -p test_collectors.py`；新增针对许可完整性与 provenance 的断言，使用已有假 pnpm fixture，不安装/升级依赖。
- 对 frozen manifests/lockfiles 比较修复前后 SHA-256，确认字节不变。
- 使用相同 Dockerfile 与锁文件重建测试镜像；从镜像导出上述两个许可目录，确认 tinypool LICENSE 与 inventory 记录仍在、原始 package.json 不在、manifest hash 与构建输入一致；复核没有 tinypool/dist 或其他执行载荷通过包装进入。
- 比较修复前后 inventory：包集合、名称版本、来源、许可与 evidence paths/hashes 应不变，只增加原 manifest provenance hash；不能靠删除整个组件记录解除告警。
- 保持相同 Trivy image/scanner 参数、正常拉取漏洞库，重跑完整 CRITICAL gate 和 SBOM。确认不存在许可 package.json 引起的这两个 component 路径，而实际运行组件仍正常被扫描。
- 原有 license smoke 仅检查三类目录存在（`scripts/self_host_smoke.py:99-107`），不足以验证许可全文与 provenance；需要 collector 回归与最终镜像目录核对。

### External references / versions

- 本轮不重复主会话正在进行的官方 advisory 核对或 SBOM 下载；外部证据来自上面的 CI run/job 与主会话已核实的 component 路径。
- 本地已安装的 tinypool 1.1.1 原始 manifest 声明仓库 `https://github.com/tinylibs/tinypool.git`、MIT；许可证原文作为包内一手证据只读核查。
- 不将版本号改写为已修复版本；当前锁定 tinypool 1.1.1 / Vitest 3.2.7 / Trivy 0.64.1，依赖风险修复需另行获准。

### Related specs

- `.trellis/spec/reven-server/backend/ci-release-contract.md:74-84`：原生 AMD64 full CI、真实测试镜像、默认安全策略、许可检查、故障清理，不放宽容器验证。
- `.trellis/spec/reven-server/backend/open-source-self-host-contract.md:70-72`：真实构建上下文/运行许可材料边界；采集不等于完成公开分发审查。
- `THIRD_PARTY_NOTICES.md:20-35,49-58` 与 `licenses/REVIEW.md`：许可原文、来源、哈希和内嵌 runtime 未完成事项须保留，本修复不作法律兼容性结论。

## Caveats / Not Found

- 未安装/升级依赖、运行镜像构建或 Trivy、提交/推送/部署；仅核查文件与本地包并写研究文档。
- “这次 Trivy 两个 component 来自许可 manifest”已由主会话 SBOM 确认；“全镜像绝无 tinypool 代码”不能从 SBOM、Dockerfile 或字符串搜索直接推出，尤其嵌入式 dsh 原生载荷不在本轮审计范围。
- 许可包装修复不会消除 builder 内原版本；不能宣称 CVE 已升级修复或开发/测试环境已无风险。
- 如果重建后仍存在真实运行载荷或 gate 仍失败，应停止并重新调查；不能追加扫描排除或虚报修复。此时需要另行决定依赖修复范围。
