# 发布包缺失许可的补充原文

这里仅保存可按固定版本追溯的上游原文，不为缺少声明的包虚构版权人或许可条件。

- `javascript/inventory.json`：从 npm 精确版本元数据中的 `gitHead` 对应源码获取许可证；
  esrecurse、https-proxy-agent、imurmurhash 的完整许可在已安装包 README 中，按原文保留。
  三个 Linux 平台包使用其相同版本 esbuild/Rollup 项目的原始许可。
- `python/inventory.json`：FastMCP-slim 4.0.5 wheel 未携带许可证，补充官方 v4.0.5 的 Apache-2.0 原文。
- `ruby/inventory.json`：14 个发布包缺失原文按精确上游 tag 补充，minitest 的完整许可从镜像内 README 原样保留；rubyzip 的 README 与 gemspec 存在许可表述冲突，显式标记 `LICENSE CONFLICT`。
- 每条证据记录原始来源、版本、SHA-256；npm 包另保留 registry 的完整性标记与可用的 gitHead。
  收集脚本仅匹配相同名称/版本的安装包，复制前核对证据校验和；升级依赖不能沿用旧版本声明。
- `khroma@2.1.0` 的 package.json 没有 license 字段，但其原始 LICENSE 明确是 MIT；记录该已核验结论。

未补齐的发布包逐项列在 [../REVIEW.md](../REVIEW.md)，不能把本目录存在当作全部依赖均已核验。
