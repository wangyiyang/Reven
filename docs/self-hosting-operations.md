# 自托管备份、恢复与升级

适用于 [自托管指南](self-hosting.md) 的 `infra/self-host/` 部署。以下 Bash 命令从仓库根目录执行，并沿用指南中选定的 `dc` 函数；本机 HTTP 模式必须保留 local override。

## 备份范围

数据库、加密主密钥和持久卷必须作为同一套备份管理。

| 数据 | 位置 | 恢复要求 |
| --- | --- | --- |
| 业务记录、RSS 状态、加密集成凭据、会话 | `postgres-data` | 使用 PostgreSQL 17 的 `pg_dump` / `pg_restore` |
| 主密钥、管理员密码、数据库密码和环境配置 | `infra/self-host/.env` | 单独加密保存；必须包含备份时的原主密钥 |
| 发布任务文件与 Agent 运行数据 | `reven-data`、`dsh-data` | 停止应用后归档，恢复时保留 UID/GID |
| 前端静态版本 | `reven-static` | 随备份保存；后续成功启动会按镜像更新 |
| TLS 私钥、证书与 Caddy 状态 | `caddy-data`、`caddy-config` | 停止 Caddy 后归档，按秘密资料保存 |
| 可追溯运行版本 | 源码提交、本地镜像 ID、Compose 文件 | 恢复兼容的代码和基础设施，不使用任意最新版本 |

COS 对象、Notion 内容、博客仓库与公众号草稿不在本机备份中；启用后分别安排这些服务的数据保护。Reven 的数据库恢复不会撤销已经发生的外部写入。

## 创建一致备份

先安排短暂停机。下面在仓库外创建私有目录，停止应用与入口后导出数据库和文件卷。脚本出错会停止；失败时先处理原因，再决定是否重新启动服务，不要把不完整目录当作可用备份。

```bash
set -e
umask 077
backup_dir="$(mktemp -d /var/tmp/reven-backup.XXXXXXXX)"
dc stop caddy reven
cp infra/self-host/.env "$backup_dir/reven.env"
git rev-parse HEAD > "$backup_dir/source-commit.txt"
reven_container="$(dc ps -a -q reven)"
caddy_container="$(dc ps -a -q caddy)"
reven_image="$(docker inspect --format '{{.Image}}' "$reven_container")"
caddy_image="$(docker inspect --format '{{.Image}}' "$caddy_container")"
printf '%s\n' "$reven_image" > "$backup_dir/reven-image-id.txt"
docker image save "$reven_image" > "$backup_dir/reven-image.tar"
dc exec -T postgres pg_dump -U reven -d reven -Fc > "$backup_dir/database.dump"
docker run --rm --network none --user 0 \
  --volumes-from "$reven_container:ro" --entrypoint tar "$reven_image" \
  -C / -czf - data srv/reven > "$backup_dir/reven-volumes.tar.gz"
docker run --rm --network none --user 0 \
  --volumes-from "$caddy_container:ro" --entrypoint tar "$caddy_image" \
  -C / -czf - data config > "$backup_dir/caddy-volumes.tar.gz"
dc exec -T postgres pg_restore --list < "$backup_dir/database.dump" > /dev/null
tar -tzf "$backup_dir/reven-volumes.tar.gz" > /dev/null
tar -tzf "$backup_dir/caddy-volumes.tar.gz" > /dev/null
dc up -d --wait
printf '备份目录：%s\n' "$backup_dir"
```

临时归档容器使用 root 仅为读写卷时保留文件属主；应用本身仍以非 root 运行。两个嵌套挂载 `/data`、`/data/dsh` 都通过 `--volumes-from` 备份。

将整套备份加密后转移到主机之外，并在密码管理器中独立保存主密钥。上述格式检查只证明归档可读，须在隔离环境实际恢复才能确认备份有效。

## 在空环境恢复

只在**空的独立 project 和卷**上执行。不要向现有生产数据库导入，不要用 `down -v` 清理运行环境。旧实例必须停止，避免两个实例同时调度和写入 Notion。

1. 在新的源码目录取出备份记录的提交。把备份中的 `reven.env` 复制为 `infra/self-host/.env`，设置权限 `600`；保留原主密钥与数据库密码。
2. 定义恢复专用的 `dc`：把指南中的 project 改为 `reven-restore`。初次演练使用 local override，并在防火墙层限制外部服务访问，先核对本地数据；不要让演练实例写真实集成目标。
3. 在当前会话将 `backup_dir` 指向已解密的、受信任的备份目录。载入保存的应用镜像，并将它标记为该 Compose project 的本地构建名：

```bash
set -e
docker image load < "$backup_dir/reven-image.tar"
docker image tag "$(cat "$backup_dir/reven-image-id.txt")" reven-restore-reven
dc create --no-build
dc up -d --wait postgres
dc exec -T postgres pg_restore --exit-on-error --no-owner \
  -U reven -d reven < "$backup_dir/database.dump"
reven_container="$(dc ps -a -q reven)"
caddy_container="$(dc ps -a -q caddy)"
reven_image="$(docker inspect --format '{{.Image}}' "$reven_container")"
caddy_image="$(docker inspect --format '{{.Image}}' "$caddy_container")"
docker run --rm -i --network none --user 0 \
  --volumes-from "$reven_container" --entrypoint tar "$reven_image" \
  -C / -xzpf - < "$backup_dir/reven-volumes.tar.gz"
docker run --rm -i --network none --user 0 \
  --volumes-from "$caddy_container" --entrypoint tar "$caddy_image" \
  -C / -xzpf - < "$backup_dir/caddy-volumes.tar.gz"
dc up -d --no-build --wait
```

`dc create` 只创建容器和卷，不启动应用，因此可以在自动迁移和调度开始前导入。恢复命令仅适用于自己生成、校验过的归档；不要以 root 解压来源不明的文件。

恢复后检查健康接口、登录、RSS 状态、集成凭据是否可解密、卷中任务数据及运行 UID。正式切换前核对已发生的 Notion / GitHub / 微信写入；旧备份可能缺少后续成功记录，不能直接假定重试安全。测试实例验证完成后停止它，再恢复正式实例的外部访问与调度。

## 升级与应用回滚

自托管更新采用源码构建，不使用维护者的 `scripts/deploy_reven.sh`。先阅读目标版本的迁移说明，确认上一版本能读取升级后的数据库，再安排升级。

1. 按上文创建并验证备份，记录当前源码提交与镜像 ID。保留该镜像，升级完成前不要执行镜像清理。
2. 获取并检出审阅过的目标提交，保持 `infra/self-host/.env`、project 名与卷不变；如配置示例有新增必填项，先补齐。
3. 在当前 Bash 会话保存旧镜像的引用，然后构建新版本：

```bash
previous_container="$(dc ps -q reven)"
docker image tag "$(docker inspect --format '{{.Image}}' "$previous_container")" \
  reven-local:before-upgrade
dc config --quiet
dc build reven
dc up -d --wait
dc ps
```

4. 验证健康、登录、静态页面和已保存的集成；观察下一次调度。备份及旧镜像保留到验证结束。

若升级失败，先停止 Reven，检查迁移是否已执行。**回滚应用不会降级数据库。** 只有确认 schema 与旧应用兼容时，才恢复备份所记录的源码提交及配套 Compose/Caddy 配置，将旧镜像标回原 project 的构建名，并启动：

```bash
dc stop reven
docker image tag reven-local:before-upgrade reven-self-host-reven
dc up -d --no-build --wait
```

上例只适用于 project 为 `reven-self-host` 的部署；若更改了 project，镜像名也必须对应。不要未经评估运行 `alembic downgrade`。迁移不兼容时，应先停止写入，在独立环境恢复升级前的完整备份，再制定切换方案，并核对备份后发生的外部交付。

## 配置变更

- 修改 `.env` 后使用 `dc up -d --force-recreate --wait reven` 使环境变量生效；仅 `restart` 不会重读容器环境。
- 在 UI 更改 Agent LLM 配置后需要 `dc restart reven`；RSS 及其他集成的日常配置按页面操作。
- 更改域名时同步修改 origin、DNS 和 Caddy 入口，重新创建相关容器后验证 HTTPS 与登录。
- 主密钥不是普通可替换密码。当前没有一键重加密流程，不要直接换值；先保留旧密钥并安排凭据迁移。
- 维护者原有 ACR digest 校验、HTTP 3001 和部署回滚继续按 [原运行手册](runbook.md) 操作，本指南不会迁移现有生产环境。
