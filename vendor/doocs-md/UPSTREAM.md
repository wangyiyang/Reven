# Doocs Markdown 上游信息

- 仓库：https://github.com/doocs/md.git
- 固定提交：`c37c1d6cc0e0a259de20305b9e4c3b59c7029da7`
- 固定提交日期：2026-05-31
- 许可证：WTFPL v2，原文见同目录 `LICENSE`

## 本地适配边界

仅同步渲染所需的 `packages/core`、`shared`、`config`、Juice 补丁和许可证。
不引入 Doocs Web/Vue 应用；Reven 的适配代码独立位于 `renderer`。
2026-09-21：排除渲染不使用的 `shared/src/configs/api.ts` 托管服务配置，
并移除 `shared/src/configs/index.ts` 对该文件的导出，避免同步上游凭据。
