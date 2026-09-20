# Node.js 运行时声明

- 版本：`v22.22.2`，对应 `infra/docker/Dockerfile` 的固定 Node 构建镜像。
- 原始许可与内嵌组件声明：[Node.js v22.22.2 LICENSE](https://github.com/nodejs/node/blob/v22.22.2/LICENSE)。本目录原样保存该文件。
- 最终镜像只复制 Node 可执行文件；声明保存在 `/opt/reven-licenses/node/LICENSE`。
- 升级 Dockerfile 的 Node 版本时，必须同时更新本目录；不能把 Node 主许可替代文件中列出的组件条款。
