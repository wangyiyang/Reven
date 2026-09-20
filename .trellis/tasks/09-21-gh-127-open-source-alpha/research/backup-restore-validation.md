# 备份恢复辅助验收

- 执行日期：2026-09-20T17:00:09+00:00。
- 结论：按 `docs/self-hosting-operations.md` 的核心命令，在独立空项目中完整恢复成功。
- 平台边界：Linux AMD64 应用/数据库/Caddy 镜像运行于 ARM64 Docker daemon，属于仿真辅助证据；不替代正式 Linux AMD64 支持验收。
- 应用镜像：`sha256:6366dea0c175911e6374ffb1985e9379704d80f92b5e0a90b067b6de6cdbef95`，复用主会话构建的 `reven:test`，未构建/发布另一份镜像。
- 测试脚本仅保存在仓库外；SHA-256：`19552dff227812373b2e9c35e7602c497fb1e3d652eff4574ca48d477bbd8e8f`。

## 隔离与测试数据

使用两个随机、互不共享卷的 `reven-backup-source-*` / `reven-backup-restore-*` Compose project。入口使用临时空闲 loopback 端口，与其他 smoke 的 8080/8443 分离。所有密码与主密钥均临时随机生成；没有读取真实部署 `.env`。

应用与 PostgreSQL 只连接 internal 网络，防止外部调用；Caddy 同时连接专用入口桥以提供 loopback 访问。测试通过真实登录与配置 API 创建一个禁用的 RSS 源和一个禁用的 `translate_baidu` 集成，后者使用假凭据。没有 Notion、飞书、博客或公众号的真实目标，也没有调用集成连接测试。

分别在 `/data/jobs`、嵌套卷 `/data/dsh`、`/srv/reven` 及两个 Caddy 状态卷写入测试标记。

## 按文档执行的步骤与结果

| 步骤 | 实际验证 | 结果 |
| --- | --- | --- |
| 停机备份 | 停止 Caddy/Reven，复制原环境配置，记录镜像 ID；`docker image save`、`pg_dump -Fc`、两个 `--volumes-from` tar 归档 | 通过 |
| 格式检查 | `pg_restore --list`，遍历两份 tar 归档；确认归档实际包含 `data/dsh/backup-marker` | 通过 |
| 备份后恢复服务 | 源项目重新启动，已有会话与禁用 RSS 记录仍可读取；随后停止整个旧实例再恢复 | 通过 |
| 空环境恢复 | `docker image load`；将保存的镜像标记为恢复 project 的本地构建名；`compose create --no-build` 后仅启动 PostgreSQL | 通过 |
| 数据与文件导入 | `pg_restore --exit-on-error --no-owner`；应用启动前以临时 root 归档容器执行 `tar -xzpf` | 通过 |
| 认证与业务数据 | 原浏览器会话访问 `/api/auth/me` 成功，恢复后的 RSS 记录 ID 与禁用状态一致 | 通过 |
| 加密记录 | 原密文的 SHA-256 保持一致，使用恢复的原主密钥解密得到测试凭据，使用错误主密钥被显式拒绝 | 通过 |
| UID 与卷权限 | 应用 UID 为 10001；三个应用标记文件内容相同、属主 UID 10001、权限 0600 | 通过 |
| Caddy 状态 | `/data` 和 `/config` 两个测试标记均恢复 | 通过 |
| 注销 | 恢复后注销成功，重放原会话 Cookie 返回 401 | 通过 |
| 清理 | 两个项目的容器、卷、网络及本次镜像别名全部清理，备份临时目录自动移除 | 通过，无清理错误 |

归档大小：数据库 69,565 字节；应用卷 17,971,367 字节；Caddy 卷 970 字节；保存的应用镜像 1,256,791,040 字节。

## 本机环境差异

1. 同一 PostgreSQL 多架构 index 在本机已有 ARM64 缓存，显式 AMD64 pull 报 `cannot overwrite digest`。为保留现存测试数据库，仅在临时 fixture 中使用相同固定 index 对应的 AMD64 子 digest：`postgres@sha256:af194ccf3e2d7fe367012c7b88ce8b816c5c889b18a5b316799a1f0d7eac746a`。产品 Compose 未修改。上游 manifest 文件 SHA-256 为 `742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193`。
2. Docker 不为仅连接 internal 网络的 Caddy 实际发布宿主端口；临时 fixture 因而使用 Caddy 双网络，应用与数据库仍无外网。此额外隔离对应文档要求的演练外部访问限制，不改变产品部署契约。
3. 本机系统 Python 为 3.9，因此辅助脚本使用项目 `.venv/bin/python`（3.12）；不影响容器内 Python 或 Ubuntu 22.04 CI 的 Python。

## 未覆盖范围

未访问真实外部集成，未恢复真实 TLS 私钥或验证生产证书链。本次 Caddy 验证针对两个状态卷的归档恢复；可信 HTTPS 的认证与证书行为由独立 self-host smoke 覆盖。未执行 schema 降级或不兼容版本回滚，也没有将恢复应用镜像等同于回滚数据库。

本次未发现备份恢复文档命令的功能缺陷。完整原生平台证据仍由主会话的 Linux AMD64 CI 提供。
