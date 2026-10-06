# 前后端统一发布到 VPS

## 目标与价值

恢复 Reven 前端与 API 在现有 VPS 上的统一发布，通过 `https://dev.wangyiyang.cc` 同源访问。前后端由同一镜像 digest 发布和回滚，停止 Vercel 的日常独立自动发布。

## 用户已确认的范围

- 用户要求“修改统一前后端发布到 VPS”，并于 2026-10-06 同意建立任务、进入规划。
- 用户随后选择选项 1：**仅恢复统一部署，基于当前线上版本制作独立补丁，不执行 main 中的 CRM/人才库业务迁移。** 本次补丁分支从当前发布版本建立，作为从 main 开发的默认约定的一次明确例外；main 中的长期修复仍通过 PR 合并。
- 应用统一部署范围不包含 Supabase/COS 托管位置迁移；保留当前 dsh、单 worker 和数据卷。
- 用户已在看到最终规划摘要后于 2026-10-06 回复“开始实施”，实施门禁已满足。

## 背景与已核实证据

- 主规划工作树基于 main `6166389772d7ea61cd562f0546ad577cb81bf275`，主工作区既有 `dogfood-output/` 不属于本任务。
- 镜像已包含前后端及对应 infra（`infra/docker/Dockerfile:44`、`:54`）；entrypoint 先迁移，再原子切换静态 current（`infra/docker/entrypoint.sh:15`、`:25`）。无需新镜像拆分或流水线。
- 线上核查：VPS 首页 404、health 200 且 db/dsh/background_runner 均 ok；Vercel 首页 200；PUBLIC_BASE_URL 已为 VPS HTTPS 域名，保留 Vercel Origin 白名单。
- 当前镜像为 ACR digest `sha256:067d44f6d0698f61e7f2ee182d05b2b2b57a349d6a5fe0c472a940c600f390d7`。该 digest 出现在成功发布 run 37336544856 中，run 源码为 v0.7.1 / `2066c3c39823bf68b4539b8c25a022b55b274bc1`；该发布版本确定为生产补丁基线。
- 生产 Caddy 缺静态路由和 Caddy 静态卷挂载（`infra/caddy/Caddyfile:17`；`infra/compose/docker-compose.yml:61`），应用静态卷仍在（`:19`）。
- 生产 Caddy 当前只在 full CI 做语法校验（`.github/workflows/ci.yml:184`），真实请求烟测使用 self-host 配置（`scripts/self_host_smoke.py:68`、`:185`）；生产配置路径未进入 backend filter（`.github/workflows/ci.yml:49`）。
- Vercel 项目 API 已核对：旧入口属于 reven-web / `prj_2wDJKDopTmLq1kgscRH1RBK3o2zR`，当前根目录默认 `.`、Node 24、`link=null`；部署 `dpl_31YGd8pwoUqpV3oBZcJcDk1QBRyA` 的 `source=cli`。当前无 Git 连接，仓库 `web/vercel.json` 的禁用配置适用于后续确实读取该目录配置的集成。
- 线上数据库为 `0024_rss_resilience`；main 的 #207 新增 0025/0026，0025 删除客户计划字段（`server/migrations/versions/0025_crm_plan_derive.py:23`）。用户已决定不随本次上线，补丁保留 v0.7.1 的应用与迁移代码。

## 要求与验收映射

| ID | 要求 | 验收 |
| --- | --- | --- |
| R1 | Caddy 恢复首页、SPA 深链接与独立 assets 静态分支；沿用已有 self-host 规则。 | A1/A2 |
| R2 | Caddy 只读共享 reven-static，继续用既有镜像产物、迁移后原子静态切换。 | A3 |
| R3 | API 独立反代，内部 /agent/* 显式 404；保留 TLS、安全头、CSRF 与 Cookie 契约。 | A4 |
| R4 | 补生产配置 backend 路径过滤；扩展既有隔离烟测，实际运行原生产路由，不改变 container 的 full-only 门禁。 | A5 |
| R5 | 关闭 Vercel Git 自动发布，VPS 为当前正式入口；同步部署文档和规范，保留历史 Vercel 部署与现有过渡配置。 | A6 |
| R6 | 生产补丁基于 v0.7.1，包含必要的 gha 构建缓存修复，不包含 main 的业务代码/迁移；main 的长期修复走 PR。 | A7/A8 |

## 验收标准

- A1：可信 HTTPS 下首页、登录页和实际 CRM/RSS 深链接均返回并加载镜像 index，刷新正常，页面 Cache-Control 为 no-cache。
- A2：index 实际引用的 JS/CSS 全部可读，MIME 正确且具有一年 immutable 缓存；缺失 assets 为 404。Caddy 直出页面/资源保留既有安全头。
- A3：真实容器核对应用/Caddy 挂载相同静态卷，应用可写、Caddy 只读；HTTP index 与部署镜像的 index/release 一致。
- A4：API 为 JSON，匿名业务接口 401，/agent/* 为 404。隔离环境验证真实登录/注销、Secure/HttpOnly/SameSite Cookie、同源写入与异源/缺头拒绝；线上验证真实登录和业务页面读取，不创建业务测试数据，不输出密码或 Cookie。
- A5：生产 Caddy/Compose 单独变更也选择 backend 回归；原生 Linux AMD64 full CI 执行生产路由请求，保持隔离数据库、随机项目、可信 CA、失败清理和既有安全策略。主线及实际补丁分支分别验证。
- A6：仓库 Vercel 配置禁用 Git 自动部署，并核实平台无持续 Git 自动发布；当前旧项目无 Git 连接，保留此状态，后续连接须检查项目实际读取的配置；维护手册不再将 Vercel 描述为唯一前端入口。保留旧域与 Origin 白名单作为故障回退入口，不删除历史项目。
- A7：补丁相对 v0.7.1 的 server/src、server/migrations、web/src、依赖及锁文件均无差异；构建出的迁移 head 仍为 0024。上线前后实际数据库 revision 均为 0024。
- A8：main 的修复经 PR 审阅合并；补丁使用未占用的新 semver tag（计划 v0.7.2），按完整 ACR digest 部署并记录源码/CI/run/digest。失败可用原 v0.7.1 digest 恢复此前 API + Vercel 入口，不执行数据库降级或改动其它 VPS 服务。

## 范围外与限制

不发布 main 中 #207 的 CRM/人才库变更，不新增/修改数据库迁移，不升级 dsh，不迁移 Supabase/COS，不拆 worker，不新增前端镜像或 Kubernetes，不删除 Vercel 历史项目，不退役 HTTP 3001 过渡入口，不删除 CSRF 白名单能力，不改无关 VPS 服务。

恢复 v0.7.1 digest 会恢复原混合部署形态（VPS 首页再次 404，旧 Vercel 页面服务恢复为使用入口），不承诺回滚后仍有 VPS 前端。旧 Vercel Cookie 不会迁移到 VPS 域，首次访问需重新登录。Vercel 的彻底删除和白名单清除留待单独决定。

## 规划收敛状态

用户拥有的上线范围决定已解决，无阻塞产品问题。技术设计、实施步骤与真实验收方案已落盘，两个上下文清单均有有效规范/研究条目。用户已批准实施，task 已切换为 in_progress；实际检查、补丁制作与发布证据在实施过程中补齐。
