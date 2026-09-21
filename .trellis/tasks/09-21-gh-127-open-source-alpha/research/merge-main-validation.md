# 合并 main #128 的验证记录

## 范围与结论

将 main 的 `7edafd737beaa39c6470c486b130f2a4434e44cb` 合入开源准备分支，保留 #128 已确认的产品收缩：RSS 采纳保存本地素材，Notion、稿件发布、renderer、Doocs、Ruby 与 bubblewrap 不恢复。

处理 8 个文本/删除冲突，并同步无文本冲突但已过时的 self-host、许可采集、贡献与使用文档。保留原创 Apache-2.0、HTTPS/CSRF/Cookie、独立源码部署与第三方声明。本记录取代早期报告对当前版本的运行结论；早期日志仍保留来源与提交。

## 合并边界

- 5 个 modify/delete 文件遵循 main 删除：renderer/package.json、两份 Doocs vendoring 脚本、UPSTREAM.md 与 config barrel。
- Dockerfile 保留 main 的精简运行依赖，同时采集当前 Web/Python/Debian 原始许可。
- self-host 删除专为退役功能增加的 AppArmor/profile/seccomp 配置，保留 Docker 默认策略、UID 10001、只读根文件系统、cap_drop、no-new-privileges 与资源限制。
- RSS smoke 通过真实 API 验证本地候选采纳、重复采纳幂等及容器重建后的 saved_at/内容/会话/卷持久化；候选为独立数据库中的确定性 fixture，不宣称真实 Feed 抓取已验收。
- 文档按本地素材流程重写；0021 不可逆迁移及整体备份恢复要求保持明确，未执行生产迁移。

## 验证进度

- 锁定依赖同步通过；未重新解析或修改锁文件。
- 23 项 self-host/CI 定向测试、Ruff/format、mypy 119 源文件与 actionlint 通过。
- Web ESLint、TypeScript、测试及构建通过；原有 MSW/Node 警告与大 chunk 提示保留。
- `sh scripts/test_deploy_reven.sh` 通过。
- 后端全量：560 passed，覆盖率 86.96%；首次运行遗漏独立测试库初始化而报错，完成 Alembic `upgrade head` 至 0021 后重跑通过，未修改业务代码规避测试。
- 许可采集 3 项回归通过；当前 workspace 依赖树排除 298 个旧缓存包。macOS 清单 383 JS / 105 Python（后者含开发依赖），不能代替最终 Linux 运行清单。
- 15 段 Shell 文档语法、Trellis implement/check 各 9 条 context 校验、`git diff --check origin/main` 通过。
- 当前树 Gitleaks 8.30.1 仍仅命中 2 条已有人工确认的测试假值/变量示例；原始报告在仓库外脱敏保存。
- GitHub 当前 required checks 已为 backend、frontend、migration、container（strict=true，GitHub Actions app 15368）；renderer 随 #128 退役，其门槛已由其他操作移除，本会话未改动分支保护。
- 合并后的原生完整容器 CI：待合并提交推送后执行。

## 仍需完成的发布验收

历史凭据材料与实际公开快照处置、当前二进制分发许可核验、真实 Feed 的完整发现/人工保存链路、公网 DNS/ACME 及公开仓库私密报告入口仍按独立证据验收。Notion 专用测试空间已不属于当前产品的验收前提。
