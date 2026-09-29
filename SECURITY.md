# 安全问题反馈

请勿在公开 Issue、PR、讨论或日志中粘贴漏洞利用细节、访问令牌、密码、Cookie、数据库连接串或用户数据。

## 私密报告

请使用 GitHub 的 [私密漏洞报告入口](https://github.com/wangyiyang/Reven/security/advisories/new)。该入口面向公开仓库，已在仓库 Security 设置中启用并验证可用。

请私密提交：受影响版本或提交、部署方式、问题影响、最小复现步骤与已脱敏的证据。复现只使用自己控制的测试环境与数据，不需要提供真实密钥。

发布修复说明或与报告者协调披露范围前请先脱敏，不把私密报告内容直接复制到公共 Issue。

若入口返回 404 或不可用，可以开一个仅包含“请启用私密漏洞报告入口”的普通 Issue；不要放漏洞内容，待私密通道可用后再提交。当前没有经确认的备用安全邮箱。

已暴露的凭据应先在服务提供方撤销或轮换；删除公开文字或代码提交无法保证清除旧副本。请保留脱敏时间线，随后通过私密通道沟通影响范围。

## 支持范围

项目处于 Alpha，安全修复优先落在当前维护的代码版本；尚无长期支持版本或承诺的响应时限。部署前阅读 [自托管指南](docs/self-hosting.md)，公网使用 HTTPS，定期备份数据库、主密钥及持久卷。

请勿将单管理员实例作为多租户服务使用。任何安全排查都不应通过公开数据库端口、移除沙箱或提升应用容器特权来“修复”错误。

## 公开前检查记录（2026-09-30）

- 已在仓库 Security 设置启用 [Private vulnerability reporting](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting/configure-for-a-repository)，并验证报告入口可用。
- 拟公开内容与完整历史完成凭据扫描复核：gitleaks 全历史扫描（18 命中）+ blob 级模式抽查，脱敏报告随仓库任务工件归档。历史 vendor 文件中的 31 个 GitHub/Gitee 值经定性为上游 `doocsmd` 水印占位值，非真实凭据；无未处理的真实凭据。
- 删除公开文字或代码提交无法保证清除旧副本；已暴露凭据应始终在服务提供方撤销或轮换。
