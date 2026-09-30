# 技术设计：历史凭据吊销与全历史扫描复核

## 决策

- **不重写历史**（方案 A，用户已确认）。已吊销凭据 = 已处理；历史中的死字符串不构成未处理凭据。
- **不使用发现的 token 调用任何 API**（避免使用泄露凭据本身）。失效性只通过两条路径确认：维护者核对本人 PAT 列表吊销；仓库转公开后 GitHub secret scanning 自动吊销 ghp_ token 作为兜底。

## 工具与命令

- 安装：`brew install gitleaks`
- 扫描（全分支 + tag，强制脱敏）：
  ```bash
  gitleaks git --redact --log-opts="--all" --report-format json \
    --report-path .trellis/tasks/09-29-secret-history-audit/research/gitleaks-report.json .
  ```
  `--redact` 对 secret 值打码，保留 rule-id / file / commit / 行号，满足 R1。
- 分诊辅助：`jq` 按 ruleID 聚合统计；个别命中用 `git show <commit>:<file>` 复核（输出时同样脱敏）。

## 分诊流程

1. 按 ruleID 聚合命中数，与已知基线对比（31 个 vendor token 应命中在 `vendor/doocs-md/shared/src/configs/api.ts` 于 e43726a..7edafd7 区间）。
2. 每个非已知命中定性：
   - **假阳性**：占位值/示例值/测试夹具（DeepSeek Key 占位值属此类）→ 报告标注排除理由；
   - **真实凭据且可吊销** → 维护者吊销，标注状态；
   - **真实凭据且不可吊销**（私钥等）→ 停止，回到父任务 R4 重启历史重写决策。
3. 报告结构：执行摘要（总数/分类数）→ 明细表（规则/位置/指纹/定性/状态）→ 吊销核对清单回执区。

## 风险与边界

- gitleaks 规则可能漏报（自定义密钥格式）；缓解：除 gitleaks 外，补一轮 `git grep` 模式抽查（`ghp_|gho_|github_pat_|sk-|AKIA|BEGIN.*PRIVATE KEY`）覆盖全历史文件快照。
- 报告文件（含指纹）落入 `.trellis` 会被 git 跟踪——指纹不含完整值，可接受；这正是 issue 要求的"脱敏检查记录"。
- 用户吊销动作是外部阻塞：扫描与报告可先完成，吊销状态以清单回执形式跟踪。
