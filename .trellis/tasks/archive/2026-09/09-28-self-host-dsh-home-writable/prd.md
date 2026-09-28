# self-host 部署修复 dsh 运行时 HOME 不可写

## Goal

修复 self-host（read_only 根文件系统）部署下 dsh Agent 运行时启动即降级的问题，使飞书机器人对话等 Agent 能力在 self-host 环境开箱可用。

## Background

2026-09-28 生产（dev.wangyiyang.cc）实测：feishu_bot 桥接 Agent 对话报 `AgentNotConfiguredError`（配置未加载，已另行解决配置录入）后，重启暴露真凶——dsh 运行时（pkg 打包的 Node）启动时需在 `$HOME/.cache/pkg/` 创建插件缓存目录，而 reven 容器 `read_only: true` 且 `$HOME=/home/reven` 位于只读根文件系统，mkdir 失败导致 boot 报 `JsonRpcError`，AgentRuntime 按降级策略置为不可用，机器人回复兜底文案"出了点问题，请稍后重试"。

服务器侧已验证修复：compose 增加 `HOME: /data/dsh`（指向已挂载的可写卷）后容器 healthy，dsh 子进程正常回调 MCP 端点，飞书对话恢复。本任务将该修复持久化回仓库，避免 self-host 用户踩同样的坑。

## Requirements

- `infra/self-host/docker-compose.yml` 的 reven 服务 `environment` 段增加 `HOME: /data/dsh`，附注释说明原因（read_only 根文件系统 + dsh 插件缓存）。
- `.trellis/spec/reven-server/backend/agent-dsh-contract.md` 补充部署契约：dsh 运行时需要可写 `$HOME`（用于 `~/.cache/pkg` 插件缓存），read_only 容器必须将 `HOME` 指向可写卷。
- 不改动 Dockerfile、不改动应用代码；部署侧一行修复。

## Acceptance Criteria

- [ ] `infra/self-host/docker-compose.yml` reven 服务包含 `HOME: /data/dsh` 及说明注释
- [ ] `agent-dsh-contract.md` 记录可写 HOME 的部署要求与故障现象（mkdir ENOENT → JsonRpcError → Agent 降级）
- [ ] compose 文件 `docker compose config` 校验通过（语法合法）
- [ ] 按 GitHub Flow 开 fix 分支、Conventional Commits、提 PR

## Notes

- 参考实现：服务器 `/opt/reven/infra/compose/docker-compose.yml` 已应用同款修复并验证（备份文件 `docker-compose.yml.bak-20260928`）。
- 曾验证 `PKG_CACHE_PATH` env 无效（该 pkg 运行时不遵循），`HOME` 重定向是唯一已验证路径。
