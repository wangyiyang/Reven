# 历史凭据吊销与全历史扫描复核

> 父任务：09-29-open-source-alpha-release（Issue #127 子任务 #1，安全阻塞项，最先做）。

## Goal

在仓库转公开前，确认全历史（361 个 commit、全部分支与 tag）中无未处理的有效凭据，完成脱敏复核记录。

## Background

- vendor/doocs-md 在 `e43726a` 引入、`7edafd7` 删除，但历史中可完整恢复 31 个凭据（15 GitHub PAT + 16 Gitee token，脱敏指纹见 `research/redacted-credential-findings.md`）。
- gitleaks 未安装，全历史从未扫描；Issue 基线提到旧 DeepSeek Key 命中为占位值（已知候选假阳性）。
- 处置路线已拍板：**方案 A——只吊销 + 扫描复核，不重写 Git 历史**（已推送 secret 视为泄露，吊销是唯一可靠处置；重写 361 个 commit 的 hash 影响 Linear 链接/PR/克隆，收益为零）。若扫描发现**不可吊销**的凭据（私钥等），再回头评估重写（R4）。

## Requirements

1. **凭据吊销核对**：31 个 token 逐一定性。GitHub PAT 由维护者核对本人 PAT 列表并吊销归属项；Gitee token 属 doocs 上游，标记"已公开暴露、不可控"，记录即可。
2. **全历史扫描**：安装 gitleaks，对全部分支 + tag 扫描（`--log-opts="--all"`），输出强制脱敏。
3. **命中分诊**：每个命中归类——(a) 31 个已知 vendor token；(b) 已知假阳性（占位值）；(c) 新增命中 → 逐个定性并处置（吊销/确认失效/排除）。
4. **脱敏报告归档**：结果仅存指纹与位置（文件/commit/规则名），不落完整值，写入 `research/secret-scan-report.md`。

## Acceptance Criteria

- [ ] 15 个 GitHub PAT 完成归属核对，属维护者的已吊销（用户动作，提供核对清单）
- [ ] gitleaks 全历史扫描完成，报告脱敏
- [ ] 所有命中完成分诊定性，无"未处理的真实凭据"遗留
- [ ] 若出现不可吊销凭据，触发历史重写重评估并回到父任务决策
- [ ] 报告归档至本子任务 research/ 目录，父任务验收标准 #2 满足

## Out of Scope

- Git 历史重写（方案 B，仅在发现不可吊销凭据时重启决策）
- .gitignore / 个人绑定清理（子任务 #2）
- 仓库转公开操作本身（子任务 #4）
