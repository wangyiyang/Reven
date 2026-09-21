# 验证结果

全部验收项于 2026-09-21 在独立 worktree 与本地测试数据库中完成。没有部署生产环境，也没有调用真实飞书或其他外部集成。

## 自动检查

| 检查 | 结果 |
| --- | --- |
| 后端全套 `pytest server/tests --cov=reven --cov-fail-under=80` | 487 passed，覆盖率 86.87% |
| 前端 `pnpm test` | 23 个文件、168 项测试通过 |
| Ruff lint / format、Mypy | 全部通过，118 个源码文件类型检查通过 |
| 前端 ESLint、TypeScript、`pnpm build` | 全部通过 |
| Alembic 全新升级、退役升级、独立进程 `alembic check` | 通过；数据库与模型无差异 |
| `sh scripts/test_deploy_reven.sh` | 通过 |
| CI / release workflow actionlint | 通过 |
| Docker 完整镜像构建 | 通过 |
| 容器运行 | UID 10001；`dsh --version` 输出 0.1.5-rc.1；应用导入通过 |
| `git diff --check`、任务 context validate | 通过 |

后端测试库使用任务专属 PostgreSQL 容器及 CREATEDB 测试角色。迁移测试逐例创建独立数据库，避免不可逆迁移影响其他用例。容器使用项目锁定的依赖与 Python 3.12，宿主测试使用 Python 3.13。

## 浏览器验收

通过真实本地 API、临时管理员与独立数据库验证：

- 登录与旧 `/articles` 链接进入 RSS 内容发现。
- 采纳候选后显示“已保存到素材库”，待审核计数减少。
- “已保存素材”显示已采纳记录；刷新后仍存在，API 含 `saved_at` 且不含 Notion 字段。
- 已保存卡片不再显示审核操作。
- 集成页仅保留飞书多维表格、飞书机器人、百度/阿里翻译、Embedding 与 Agent LLM 六项。
- 系统页显示数据库和 RSS 发现状态；品牌页保留档案、素材、模板。
- 桌面及 390px 手机宽度页面正常，手机无横向溢出，浏览器无错误。

飞书采纳共用本地保存服务，由回调、权限、幂等、并发与端到端测试覆盖；没有向真实飞书发送消息。

## 审阅与限制

Trellis check agent 完成跨层审阅。已修复独立 Alembic 环境漏载认证模型、迁移日志配置关闭应用 logger、残留规范引用和旧部署夹具；无未修复的阻塞问题。

检查仍有依赖弃用警告、既有前端 SOP 测试 MSW 警告，以及 Vite 单包超过 500 kB 的提示，均不影响通过结果。

迁移 0021 会清理退役数据与集成配置，且明确拒绝降级；符合用户不保留历史数据的决定。迁移仅在隔离本地数据库中验证，生产尚未执行。
