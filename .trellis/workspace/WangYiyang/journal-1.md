# Journal - WangYiyang (Part 1)

> AI development session journal
> Started: 2026-08-19

---



## Session 1: 应用内登录替换 Caddy basic_auth

**Date**: 2026-08-19
**Task**: 应用内登录替换 Caddy basic_auth
**Package**: web
**Branch**: `main`

### Summary

grilling 访谈收敛需求后经 Trellis 任务 08-19-app-login 实现：单账号密码登录（login/logout/me + 会话表 + 7 天滑动续期 + 5 次失败锁 15 分钟 + fail-closed 中间件），前端 /login 页与 401 回跳、登出按钮，移除 Caddy basic_auth 并同步 smoke/runbook/CI。验证：服务端 560 passed、前端 67 passed、tsc/build/ruff 通过。同轮提交纳入 Trellis 脚手架。

### Git Commits

| Hash | Message |
|------|---------|
| `1e50372` | (see git log) |
| `38c6fbb` | (see git log) |

### Status

[OK] **Completed**


## Session 2: 交付一人公司 CRM MVP

**Date**: 2026-08-25
**Task**: 交付一人公司 CRM MVP
**Package**: web
**Branch**: `codex/crm-mvp`

### Summary

完成客户、联系人、跟进时间线、当前行动与到期筛选的全栈实现；新增 0013_crm 迁移、API/前端回归测试和 CRM 可执行契约。全量后端覆盖率 85.90%，前端 132 个用例通过，并完成桌面、移动端与深色模式浏览器验收。

### Git Commits

| Hash | Message |
|------|---------|
| `e9b25a4` | (see git log) |
| `abb2746` | (see git log) |
| `bed93c9` | (see git log) |

### Status

[OK] **Completed**


## Session 3: 人才库（Talents）模块 MVP 落地

**Date**: 2026-08-26
**Task**: 人才库（Talents）模块 MVP 落地
**Package**: web
**Branch**: `main`

### Summary

从 git pull 冲突切入：本地未提交的旧 CRM/talents/reminders 实现与远端 #84 冲突，备份到 ~/Reven-local-backup-20260826 后放弃本地、对齐远端。随后立项 08-26-talents-mvp，经 grilling 确认设计（B 类自由职业者对接为骨架 + C 类跟进机制；tags/费率/评分结构化；砍 domain 与 Notion 耦合；不做提醒模块），按 CRM #84 风格实现后端 + Web 前端并通过质检（修复 tags 显式 null 穿透 500 问题）。沉淀 talents-contract.md 规范。pytest 660 过、pnpm test 154 过、mypy/ruff/build 全绿。

### Git Commits

| Hash | Message |
|------|---------|
| `e368e38` | (see git log) |

### Status

[OK] **Completed**


## Session 4: RSS 配置拆分：源/关键词独立路由 + 可折叠子菜单

**Date**: 2026-08-31
**Task**: RSS 配置拆分：源/关键词独立路由 + 可折叠子菜单
**Package**: web
**Branch**: `feat/rss-settings-split`

### Summary

grilling 收敛：关键词维持全局，/rss 拆为 /rss/sources + /rss/keywords 独立路由；中途改选可折叠子菜单（桌面折叠分组、移动端 tab 平铺）。修复搬迁引入的回归（onClick 丢箭头函数致 Radix 对话框自开 aria-hidden 全应用，5 测试挂），并用函数级 md5 比对验证搬迁代码与原件逐字节一致。trellis-check 复核通过，156 测试 + lint + tsc 全绿；spec 沉淀 AppShell 导航分组约定。

### Git Commits

| Hash | Message |
|------|---------|
| `cc962ec` | (see git log) |

### Status

[OK] **Completed**

## Session 5: 入口迁移 HTTP 单端口 3001 + 部署回滚加固 + 生产事故处置

**Date**: 2026-08-31 ~ 2026-09-01
**Task**: 入口切换 HTTP 单端口 3001 并加固部署回滚
**Package**: infra
**Branch**: `feat/http-single-port-3001`、`fix/caddy-cap-net-bind-service`

### Summary

动机：宿主机多 HTTP 服务按域名+端口访问，HSTS 按主机名生效会打挂其他服务（#90 切 HTTP-only 的根因），80 不应特殊对待。实施：入口 80→3001（Caddyfile/compose/4 处默认值/7 测试文件/文档），回滚加固（reload_caddy 拆为在跑 reload / 不在跑 up -d --no-deps 尽力拉起）。部署事故链：#90 起三次部署连败，根因是服务器 .env 的 PUBLIC_BASE_URL 滞留 https 旧值，新镜像校验拒绝启动；本机 docker logs 实锤后改 .env 重部成功。次生事故：删除 cap_add 后 Caddy 崩溃循环——官方镜像二进制带 cap_net_bind_service=ep filecap，bounding set 缺失时 execve EPERM，PR #93 恢复并用 e2e 断言锁定。

### Git Commits

| Hash | Message |
|------|---------|
| `26f24f2` | feat(infra)!: 入口迁移 HTTP 单端口 3001 + 回滚加固 (#92) |
| `a5d9176` | fix(infra): 恢复 Caddy NET_BIND_SERVICE（#93） |

### Lessons

- 镜像配置校验约束变化时，服务器 .env 必须随发布同步；已固化进 runbook 第 7 节发布前置动作
- 移除容器 capability 前先 getcap 检查二进制 filecap；安全收敛需在真实 compose 环境实测，CI 的 Caddyfile 语法校验覆盖不了
- 部署脚本 restore 不能假设容器在跑（本次实弹验证了 --no-deps 拉起路径）

### Status

[OK] **Completed**（PR #93 待合并；生产已恢复并验收通过）
