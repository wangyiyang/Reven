# 当前许可核验记录（合并 #128 后）

本记录对应合入 `7edafd7` 后的 RSS 本地素材工作台。旧稿件发布、Doocs/renderer、Ruby 与独立 Node 运行依赖已经退役；[旧核验记录](history/before-local-rss.md) 保留为历史证据，不用于当前发布验收。

## 当前已核实范围

- 原创代码继续采用 Apache-2.0，服务端 wheel 打包原文的配置保留。
- Trellis 0.6.15 原始 AGPL/COPYRIGHT 及 213 个模板路径记录保留；配置清单已按仅有 web/server 的当前包布局更新。
- 三个 Fontsource 5.3.0 原文仍随 Web 产物交付：Inter、JetBrains Mono、Noto Sans SC 均保留字体版权及 OFL-1.1 全文。
- 对合并后的锁文件执行 frozen 安装后，在 macOS ARM64 按当前 workspace 已安装依赖树采集了 **383 个 JS 名称/版本**，全部能与当前 pnpm-lock.yaml 对应。旧虚拟 store 中的 298 个退役包未被采入。
- 本机 Python `--all-packages` 环境采集了 **105 个分发包**，使用 FastMCP 补充原文后无缺原文项；该数量含开发依赖，不是最终镜像 `--no-dev` runtime 数量。
- Python/JS 补充证据按名称、版本匹配并核对 SHA-256。已从当前材料移除 Ruby、khroma 和 https-proxy-agent 5.0.1 的退役补充原文。

本轮采集对应的锁文件 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `pnpm-lock.yaml` | `5a95f1e41576fc671742f221deb0c771aa10864fc73c1b44ce2842f4f8df6e7f` |
| `uv.lock` | `11c39748dfa2076f5b15ba40bcc3f01f868c782e357ba95b39e032d043b53f1a` |

## 当前 JS 完整原文待核实项

以下 8 项属于当前 workspace 安装依赖超集；实际 Web bundle 是否含其代码仍需按产物核对。已检查安装包及能定位的精确版本上游源码；缺原文不等于可以忽略版权条件。

| 名称 | 版本 | 发布者声明 |
| --- | --- | --- |
| `@humanfs/types` | `0.15.0` | Apache-2.0 |
| `@open-draft/deferred-promise` | `2.2.0` | MIT |
| `is-node-process` | `1.2.0` | MIT |
| `keyv` | `4.5.4` | MIT |
| `natural-compare` | `1.4.0` | MIT |
| `react-remove-scroll-bar` | `2.3.8` | MIT |
| `stackback` | `0.0.2` | MIT |
| `strict-event-emitter` | `0.5.1` | MIT |

## DeepSeek Harness 0.1.5rc1 的具体边界

安装的 runtime wheel 含原生 dsh、ripgrep sidecar、MIT LICENSE 与 THIRD_PARTY_NOTICES.md，采集脚本保留这些原文。
上游 NOTICE 自述只列直接依赖，并披露整个项目的 Claude Agent SDK / Claude Code 平台载荷。不能把这份全项目声明直接当作 Python wheel 的实际载荷清单。

进一步按固定 [dsh-v0.1.5-rc.1](https://github.com/deepseek-ai/deepseek-harness/tree/dsh-v0.1.5-rc.1) 核对：

- 从 `python/sdk-runtime/package.json` 对应的 lockfile importer 沿生产/可选依赖遍历，共 246 个 workspace importer、322 个外部 snapshot，全部边均能解析。
- 这个闭包含 `@anthropic-ai/sdk@0.123.0`，不含 `@anthropic-ai/claude-agent-sdk` 或其官方 CLI 平台包。因此没有依据把 Reven wheel 判定为携带 Claude Code 专有载荷。
- 构建脚本使用 Node 24 SEA、`@yao-pkg/pkg`、原生插件与 ripgrep，Web frontend 的预构建资源也加入可执行文件。当前 Web 构建使用的外部 Node 不进入最终镜像；此内嵌 Node 24 的版本和声明仍需单独核验。
- 尚未从最终 Linux wheel 中导出并逐项核对上述 322 项、嵌入 Node 的精确 patch 版本、原生插件与前端资源许可原文；wheel 自带 NOTICE 的依赖表不等于这些组件的完整原文集合。这是重新分发该二进制时的具体未完成项。

复查来源（均为固定 tag，不使用 master 推断已锁定 wheel）：

- [SDK runtime 依赖根](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/python/sdk-runtime/package.json)
- [锁定依赖](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/pnpm-lock.yaml)
- [可执行文件打包规则](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/scripts/build-exe-for-python-sdk.ts)

## 当前最终镜像的验收边界

Dockerfile 仅保留 `javascript`、`python`、`system` 三类许可采集；Debian 新增安装集为 ca-certificates、tini、util-linux。
合并后的 Linux AMD64 原生构建需重新产出并核对实际运行依赖清单、平台、证据哈希和最终镜像 digest。旧镜像的 683 JS / 96 Python / 99 Ruby / 188 Debian 数量、rubyzip 冲突及沙箱组件结论均不适用于当前镜像。
DeepSeek 内嵌组件原文、当前 JS 缺原文项、GPL/LGPL 等对应源码交付和新镜像许可扫描继续按实际产物验收。
源代码 checkout 不包含 node_modules、.venv 或这些预编译第三方可执行文件；源码公开与二进制镜像重新分发分别验收。
