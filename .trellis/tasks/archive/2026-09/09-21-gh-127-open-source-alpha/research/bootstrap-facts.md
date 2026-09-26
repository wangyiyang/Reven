# 开源 Alpha 自托管条件调查

2026-09-21，只读调查，基线 `776167540c5d6935d7462b0ad9d3f9c1bf2923b2`。未运行新部署，未读取真实 `.env`，未进行对外写入。

## 数据库与初始化

- `server/src/reven/db.py:16` 通过 SQLAlchemy + asyncpg 直连数据库。
- 未发现 Supabase Auth、Storage、Realtime 或额外扩展调用；迁移使用常规 PostgreSQL 类型。
- `.github/workflows/ci.yml:67` 使用 PostgreSQL 17 执行后端测试及迁移。
- `infra/compose/docker-compose.yml:1` 目前仅装配 Reven 与 Caddy，可通过通用 Compose 增加 PostgreSQL、数据卷和健康依赖。
- `infra/docker/entrypoint.sh:15` 已执行 Alembic 迁移，失败时停止启动，无需重复设计初始化流程。
- `server/src/reven/security/secrets.py:21` 要求 Base64 编码的 32 字节主密钥；首次配置须生成并持久保存。

## 外部集成边界

- `server/src/reven/config.py:14` 的基础必填配置是数据库、主密钥和管理员密码。
- `server/src/reven/agent/config.py:36` 在缺少 Agent 凭据时降级。
- `server/src/reven/rss/factory.py:214` 的 RSS Inbox 推送依赖 Notion；AI 筛选、翻译及通知分别依赖对应集成。
- `server/src/reven/content_sync/configured.py:74` 在完整稿件归档前无条件构造 COS store，不能把“无云账号能启动”扩写为“无云账号能运行全部链路”。

## 沙箱与平台

- `server/src/reven/publishing/sandbox.py:30` 要求 Linux bubblewrap 与 user namespace，不可用时显式失败。
- `infra/compose/docker-compose.yml:23` 提供自定义 seccomp；CI 在 `.github/workflows/ci.yml:174` 另有 Ubuntu AppArmor 调整与沙箱烟测配置。
- `.github/workflows/release.yml:44`、`:69` 使用普通 Docker 构建，未配置多平台发布矩阵。
- `infra/blog/runtime/Gemfile.lock:281` 存在 aarch64-linux 依赖记录，但不足以证明整个镜像及沙箱在 ARM64 或 Docker Desktop 可用。

## 规划影响

- 标准 PostgreSQL 及现有迁移入口可直接复用，属于证据明确的实施选择。
- 首次核心流程已由用户确定为 RSS → 人工筛选 → Notion，不扩展为完全脱离第三方服务运行。
- 建议 Alpha 先限定正式支持 Linux AMD64，并列出沙箱宿主要求；支持承诺待用户确认。

## 许可证参考

- Apache-2.0：https://choosealicense.com/licenses/apache-2.0/
- MIT：https://choosealicense.com/licenses/mit/

两者均符合允许商业使用和闭源衍生的方向；Apache-2.0 明确包含专利授权，并有保留声明及标记修改的条件。许可证选择、原创代码权属及依赖分发审查仍需完成。
