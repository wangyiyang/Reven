# 版权与第三方声明

Copyright 2026 Wang Yiyang.

Reven 原创应用代码按根目录 [LICENSE](LICENSE) 中的 Apache License 2.0 授权。
第三方代码、工具、字体及依赖保留各自许可；根许可证不会替代下列声明。
本文件记录分发边界与证据位置，不代表所有依赖已通过许可兼容性或对应源码义务审查。

## 源码中的第三方作品

| 组件 | 固定来源 | 许可、改动及声明位置 |
| --- | --- | --- |
| Doocs Markdown 渲染组件 | [doocs/md `c37c1d6`](https://github.com/doocs/md/tree/c37c1d6cc0e0a259de20305b9e4c3b59c7029da7) | `vendor/doocs-md/LICENSE`：WTFPL v2，Copyright 2025 Doocs。同步范围及 2026-09-21 的服务配置移除见 `vendor/doocs-md/UPSTREAM.md`。 |
| Juice 11.1.1 补丁 | `vendor/doocs-md/patches/juice@11.1.1.patch` | 补丁来自上述 Doocs 提交；Juice 本身及其依赖保留各自许可证，不能以 WTFPL 替代。构建时收集 Juice 包内原文。 |
| Trellis 0.6.15 工具与模板 | [mindfold-ai/Trellis v0.6.15](https://github.com/mindfold-ai/Trellis/tree/v0.6.15) | AGPL，Copyright 2026 Mindfold LLC。原文、版本表述差异、213 个文件的来源及修改记录见 `licenses/trellis/`。开发工具不进入应用运行镜像。 |
| Reven AppArmor 宿主策略 | [Moby v28.0.4](https://github.com/moby/moby/blob/v28.0.4/profiles/apparmor/template.go) | 基于默认模板局部修改，Apache-2.0；原始 LICENSE/NOTICE、来源和修改说明见 `infra/self-host/apparmor/`。 |

第三方工具文件与 Reven 的原创任务记录、业务规范和应用代码分别授权；不能仅凭目录名称判定版权归属。
分发修改后的 Trellis 工具时保留上游声明、对应源码及修改记录。

## 应用构建与镜像内的声明

Dockerfile 在构建时采集当前平台实际安装包的许可文件、版权/NOTICE 原文、版本、来源元数据及 SHA-256。
清单包含开发依赖超集，不能据此声称每个列出的包都进入了 JS bundle；它也不覆盖未安装的其他平台可选包。

| 分发物 | 可定位的声明与版本证据 |
| --- | --- |
| Reven 原创代码 | 镜像 `/opt/reven-licenses/LICENSE` 与本文件；服务端 wheel 中的 `reven/LICENSE` |
| Web JS 与字体、renderer bundle | `/opt/reven-licenses/javascript/inventory.json` 和 `packages/` 中的原始文件；Web 静态目录同时提供 `/licenses/javascript/`、`/licenses/LICENSE` 及本文件 |
| Inter、JetBrains Mono、Noto Sans SC | 锁定的 `@fontsource/*` 均为 5.3.0，实际包内为 OFL-1.1；原始字体版权及完整 OFL 文本随上述 `javascript/packages/@fontsource__<name>@5.3.0/LICENSE` 交付 |
| Node.js 22.22.2 | `/opt/reven-licenses/node/LICENSE`：原样保留该版本 Node 主许可和内嵌组件声明；更新 Node 时同步更新 `licenses/node/` |
| Doocs 与 Juice 补丁 | `/opt/reven-licenses/doocs/`；Web 静态目录另提供 `/licenses/doocs/` |
| Python 及安装包 | `/opt/reven-licenses/python/inventory.json`，原始 dist-info / 组件许可文件，以及 `python-runtime/LICENSE.txt`；Python 运行环境保留各包原文件 |
| Ruby blog bundle 与 Bundler | `/opt/reven-licenses/ruby/inventory.json` 和收集的 gem 声明；运行镜像还保留 `/opt/reven-blog/vendor/bundle/` |
| Debian 系统包 | `/opt/reven-licenses/system/inventory.json` 记录实际安装版本与 source package/version，复制对应 copyright；原文件仍在 `/usr/share/doc/`，通用许可证仍在 `/usr/share/common-licenses/` |

包清单中的 `UNKNOWN`、缺失许可证原文或 `review` 字段必须人工处理，不能自动改写为 MIT。
版权原文与许可证目录应随单独复制的 JS、字体、renderer 或镜像继续分发。
直接执行 `pnpm build` 仅生成开发构建；对外分发其产物前也需按下方命令生成、随包提供声明。

Caddy 与 PostgreSQL 服务由自托管 Compose 直接从各自官方镜像仓库获取，固定引用见 Compose 文件。
本仓库未重新托管这些镜像；重新托管者仍需检查镜像内部组件及相应许可义务。

## 可重复的采集

在安装锁定依赖的仓库根目录执行，输出到仓库外；不要将本机平台结果代替 Linux AMD64 发布镜像的清单：

```sh
node scripts/licenses/collect-js.mjs . /tmp/reven-licenses/javascript
.venv/bin/python scripts/licenses/collect-runtime.py python /tmp/reven-licenses/python
```

Ruby 与 Debian 采集在最终镜像构建阶段执行，使用镜像内的实际 bundle 和 dpkg 状态。
重新分发前还需对最终镜像 digest 进行许可扫描、核对嵌入式二进制组件和对应源码交付，
不能用 SBOM 或本清单替代上述工作。

具体已核对的版本、补充原文以及剩余问题见 [licenses/REVIEW.md](licenses/REVIEW.md)。

## 公开发布前仍需核验

- 固定 Linux AMD64 最终镜像的全部许可原文、特殊条款及组件兼容性，特别是 `deepseek-harness-runtime-bin` 内嵌的运行时/原生组件。
- GPL/LGPL/AGPL 等要求的对应源码、可重新链接材料或其他适用交付方式；系统 copyright 文件和上游 URL 本身不等于履行了所有源码义务。
- Trellis 上游 `COPYRIGHT` 的 v3-or-later 与 CLI manifest 的 `AGPL-3.0-only` 表述差异，以及模板生成差异。
- 缺失/含糊的元数据和许可证文件、未安装的平台可选包；任何新增平台必须重新核验。

未完成这些核验前，不能以新增根 LICENSE 或采集脚本作为“整个仓库及镜像已具备公开分发条件”的结论。
