> 历史证据：以下记录对应 #128 移除旧发布链路之前的应用与镜像。包数量、Doocs/Ruby/独立 Node 路径及风险不适用于当前版本；当前范围见 ../REVIEW.md。

# 许可核验记录（2026-09-21）

源码许可与构建时原文采集已落地；以下记录区分已核实事实和具体未闭合的分发问题。

## 已核实

- Reven wheel 已验证 `License-Expression: Apache-2.0`、Wang Yiyang 署名及 `reven/LICENSE`。
- Trellis 固定 0.6.15 的 213 条模板路径、原始 AGPL/COPYRIGHT 和本地适配记录已保存于 `trellis/`。
- Doocs 固定提交原文保留；不参与渲染的服务配置删除后，防回灌/失败恢复测试与 renderer 39 个测试均通过。
- Linux AMD64 测试镜像实际采集：683 个已安装 JS 名称/版本（构建依赖超集）、96 个 Python runtime 分发包、99 个 Ruby bundle/Bundler 包、188 个 Debian 包。Python 和 Debian 均有许可原文证据；JS 剩余 14 项见下表。
- 本机 macOS ARM64 的早期采集仅用于辅助核对，未代替 Linux 镜像证据。
- 三个 Fontsource 5.3.0 的原始 LICENSE 已逐份核对：Inter、JetBrains Mono、Noto Sans SC 均保留字体版权及 OFL-1.1 全文。
- khroma 2.1.0 缺少 manifest 的 license 字段，但其包内/LICENSE 原文明确 MIT，已记录证据；Python exceptiongroup、jaraco.classes、markdown-it-py、mdurl 的旧分类器明确 MIT，pathspec 明确 MPL-2.0。
- 发布包中遗漏的 FastMCP-slim 4.0.5 原文、7 个 JS 包的上游原文/README 许可和 3 个 Linux 平台包的同版本共享许可已补充，见 `supplemental/`。

## 缺失完整原文的 JS 发布包

以下包仍有明确的 license 元数据；“缺失”指本次未找到可按该版本核对的完整授权原文，不能伪造版权行。
已检查安装包；对有 gitHead 的包进一步查询了该提交的完整源码树，对无 gitHead 的包检查了可定位的版本 tag。
部分上游树本身只包含 README 的简短声明；部分历史 tag/commit 已不可获取。它们来自安装包超集，实际 bundle 是否分发对应代码仍需按产物核对。

| 名称 | 版本 | 发布者声明 | 当前状态 |
| --- | --- | --- | --- |
| `@antv/event-emitter` | `0.1.3` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `@humanfs/types` | `0.15.0` | Apache-2.0 | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `@open-draft/deferred-promise` | `2.2.0` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `agent-base` | `6.0.2` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `boolbase` | `1.0.0` | ISC | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `is-node-process` | `1.2.0` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `keyv` | `4.5.4` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `launder` | `1.7.1` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `measury` | `0.1.5` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `natural-compare` | `1.4.0` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `react-remove-scroll-bar` | `2.3.8` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `slick` | `1.12.2` | MIT (http://mootools.net/license.txt) | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `stackback` | `0.0.2` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |
| `strict-event-emitter` | `0.5.1` | MIT | 完整原文未核实；保留 manifest 与具体版本，发布相关二进制/JS 产物前解决 |


## Ruby bundle 原文与许可冲突

对 Linux AMD64 镜像初始标记的 21 项逐项核对后，20 项已解决：

- i18n 1.15.2、activesupport 7.2.3.2、execjs 2.10.1、sass 3.7.4、unicode-display_width 1.8.0 自带 `MIT-LICENSE` 或 `MIT-LICENSE.txt`；采集器现已识别该文件名，并有回归测试。
- minitest 5.27.0 的完整 MIT 授权与版权在包内 `README.rdoc`，已按原文保留。
- 其余 14 个包从与锁定版本对应的上游 tag 补齐原文：coffee-script-source、jekyll-sass-converter、jekyll-watch、jekyll-coffeescript、jekyll-default-layout、jekyll-github-metadata、jekyll-include-cache、jekyll-mentions、jekyll-optional-front-matter、jekyll-readme-index、jekyll-relative-links、jekyll-remote-theme、jemoji、github-pages。精确版本、来源和 SHA-256 见 `supplemental/ruby/inventory.json`。

**rubyzip 2.4.1 存在具体许可表述冲突**：gemspec 声明 `BSD 2-Clause`，但同版本 [README](https://github.com/rubyzip/rubyzip/blob/v2.4.1/README.md) 和 [源文件版权注释](https://github.com/rubyzip/rubyzip/blob/v2.4.1/lib/zip.rb) 声明按 Ruby license 授权；该 tag 没有独立 LICENSE。
已原样保留 README，并将 inventory 的 review 标为 `LICENSE CONFLICT`，没有自动认定只适用 BSD 或将短声明冒充完整原文。分发该 gem 前仍需核对适用许可的准确文本及上游表述。

## DeepSeek Harness 0.1.5rc1 的具体边界

安装的 runtime wheel 含原生 dsh、ripgrep sidecar、MIT LICENSE 与 THIRD_PARTY_NOTICES.md，采集脚本保留这些原文。
上游 NOTICE 自述只列直接依赖，并披露整个项目的 Claude Agent SDK / Claude Code 平台载荷。不能把这份全项目声明直接当作 Python wheel 的实际载荷清单。

进一步按固定 [dsh-v0.1.5-rc.1](https://github.com/deepseek-ai/deepseek-harness/tree/dsh-v0.1.5-rc.1) 核对：

- 从 `python/sdk-runtime/package.json` 对应的 lockfile importer 沿生产/可选依赖遍历，共 246 个 workspace importer、322 个外部 snapshot，全部边均能解析。
- 这个闭包含 `@anthropic-ai/sdk@0.123.0`，不含 `@anthropic-ai/claude-agent-sdk` 或其官方 CLI 平台包。因此没有依据把 Reven wheel 判定为携带 Claude Code 专有载荷。
- 构建脚本使用 Node 24 SEA、`@yao-pkg/pkg`、原生插件与 ripgrep，Web frontend 的预构建资源也加入可执行文件。Reven 单独复制的 Node 22.22.2 许可证不能代替此嵌入 Node 24 的版本声明。
- 尚未从最终 Linux wheel 中导出并逐项核对上述 322 项、嵌入 Node 的精确 patch 版本、原生插件与前端资源许可原文；wheel 自带 NOTICE 的依赖表不等于这些组件的完整原文集合。这是重新分发该二进制时的具体未完成项。

复查来源（均为固定 tag，不使用 master 推断已锁定 wheel）：

- [SDK runtime 依赖根](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/python/sdk-runtime/package.json)
- [锁定依赖](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/pnpm-lock.yaml)
- [可执行文件打包规则](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/scripts/build-exe-for-python-sdk.ts)

## 最终镜像核验

测试基线为 Linux AMD64 本地镜像 `sha256:6366dea0c175911e6374ffb1985e9379704d80f92b5e0a90b067b6de6cdbef95`。
在该镜像中只读挂载最新采集器和 Ruby 补充原文重新执行，已验证 99 项中 98 项有原文证据，另 1 项准确标为上述许可冲突；新构建会通过 Dockerfile 自动执行同一采集步骤。
最终镜像在各生态 inventory.json 中记录实际平台、版本与证据哈希；重新发布的 digest 仍需单独验收。
GPL/LGPL 等对应源码交付以及最终 digest 的许可扫描继续按该镜像的发布验收核对。
源代码 checkout 不包含 node_modules、.venv 或这些预编译第三方可执行文件；源码公开与二进制镜像重新分发应分别验收。
