# 全历史密钥扫描报告（脱敏）

- 日期：2026-09-29
- 基线：main（含全部分支与 tag，ref 可达 361 个 commit）
- 工具：gitleaks 8.30.1（`gitleaks git --redact --log-opts="--all"`）+ blob 级模式抽查（2865 个唯一 blob，覆盖历史上每个文件版本的全部内容）

## 执行摘要

| 扫描路 | 命中 | 定性 | 未处理真实凭据 |
|---|---|---|---|
| gitleaks 规则 | 18 | 15 已知 vendor 值 + 3 假阳性 | 0 |
| blob 模式抽查 | 1 | 已知 DeepSeek 占位值 | 0 |
| 合计 | 19 | — | **0** |

结论：**全历史未发现需处理的真实凭据，方案 A（不重写历史）成立。**

## 明细

### 1. vendor/doocs-md 凭据（15 GitHub + 16 Gitee）

- 位置：`vendor/doocs-md/shared/src/configs/api.ts`，引入 `e43726a`，文件删除于 `7edafd7`（#128），历史可恢复。
- 定性：31 个值全部内嵌 `doocsmd` 字面水印（Gitee 固定 offset=15，len=39；GitHub offset=17/18/19，len=40），非随机产出，判定为 **doocs 上游水印占位值，无真实凭据效力**。
- 处置：无需吊销（无对象可吊销）。维护者核对本人 PAT 列表与 15 个指纹无交集（清单见 `redacted-credential-findings.md`）；仓库转公开后 GitHub secret scanning 对 ghp_ 形态值自动复核，作为兜底。

### 2. 假阳性（3 项，排除并记录理由）

| 规则 | 位置 | 理由 |
|---|---|---|
| generic-api-key ×2 | `server/tests/api/test_integrations_embedding_translation.py` @ `4474590a`、`0cb26074` | 测试夹具占位值（`AKIDexample`/`tencent-key-8888` 等），非凭据 |
| curl-auth-user ×1 | `docs/superpowers/plans/2026-07-29-editorial-publishing-mvp.md` @ `60e86637` | 文档示例中的环境变量引用（`${REVEN_BASIC_AUTH_USER:?}`），无实际凭据；附带发现个人域名残留，移交子任务 #2 |

### 3. 模式抽查补充命中（1 项）

- `sk-your_deepseek_api_key_here`：DeepSeek 占位值，与 Issue 基线记录一致，排除。

### 4. 抽查未命中项（无发现）

`github_pat_` / `gho_` / `ghs_` / `AKIA…` / Slack token / `BEGIN … PRIVATE KEY` 全历史零命中。

## 覆盖度说明

gitleaks 扫描 324 个有变更的 commit（其余为合并/空提交）；blob 级抽查覆盖 2865 个唯一对象，即历史上存在过的每个文件版本，双路交叉无盲区。gitee 形态 token 无对应 gitleaks 规则，由 blob 抽查兜底（16/16 命中已知清单，无新增）。

## 维护者回执区（Issue 验收 #2 证据）

- [ ] 15 个 GitHub PAT 指纹与本人 PAT 列表核对完毕，无交集 / 有交集并已吊销（勾选项由维护者确认）
- [ ] 仓库转公开后确认 GitHub secret scanning 无新增告警（或收到 doocs 水印值自动撤销通知属预期）
