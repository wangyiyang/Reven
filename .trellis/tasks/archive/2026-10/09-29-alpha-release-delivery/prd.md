# Alpha 发布说明与安全渠道

> 父任务：09-29-open-source-alpha-release（Issue #127 子任务 #4）。

## Goal

完成开源 Alpha 的对外交付：CHANGELOG/Release notes、GitHub Release 实体、SECURITY.md 渠道落地。

## Background

- 仓库已于 2026-09-29 转公开；#157/#158 已合并，开源准备（许可、扫描、清理、GHCR）完成。
- SECURITY.md 的私密漏洞报告入口此前因仓库私有不可用；API 实测对个人账户仓库不生效（PATCH 200 但状态不变），需手动启用。
- 现有 tag v0.1.0–v0.4.1 无 Release 实体；v0.4.1 不含开源准备提交。

## Requirements

1. **CHANGELOG.md**：Alpha 版条目（定位、安装双路径、已知限制）+ 历史版本简表。
2. **SECURITY.md**：私密报告入口状态更新为已启用（以实际启用+GET 验证为前提）；维护者公开前检查清单按现状勾销（扫描已完成、凭据定性见脱敏报告）。
3. **GitHub Release**：在含开源准备的 main 上打新 tag（建议 v0.5.0，触发完整 release 流水线含 GHCR 推送与生产部署，**需维护者确认**），流水线产出 digest 后创建 Release，附镜像 digest 与文档链接。
4. **GHCR 包可见性**：首次推送后确认/设置为 public（手动，Package settings → Change visibility）。

## Acceptance Criteria

- [ ] CHANGELOG.md 与 Release notes 内容一致、随 PR 合入
- [ ] GET /private-vulnerability-reporting 返回 enabled:true（手动启用后验证）
- [ ] 新 tag 的 Release 流水线成功，GHCR digest 与 ACR 一致并写入 Release
- [ ] GHCR 包可匿名拉取（docker pull 验证）

## Out of Scope

- 干净环境验收（子任务 #5）
- 历史 tag 补 Release 说明（非阻塞，Alpha 之后按需补）
