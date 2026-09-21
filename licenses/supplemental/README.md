# 发布包缺失许可的补充原文

这里仅保存当前锁定依赖可按固定版本追溯的上游原文，不为缺少声明的包虚构版权人或许可条件。

- `javascript/inventory.json`：从 npm 精确版本元数据中的 `gitHead` 对应源码获取许可证；esrecurse、imurmurhash 的完整许可在已安装包 README 中，按原文保留。三个 Linux 平台包使用其相同版本 esbuild/Rollup 项目的原始许可。
- `python/inventory.json`：FastMCP-slim 4.0.5 wheel 未携带许可证，补充官方 v4.0.5 的 Apache-2.0 原文。
- 每条证据记录原始来源、版本、SHA-256；npm 包另保留 registry 的完整性标记与可用的 gitHead。
  收集脚本仅匹配相同名称/版本的安装包，复制前核对证据校验和；升级依赖不能沿用旧版本声明。

已随 #128 退役的 Ruby bundle、https-proxy-agent 5.0.1、khroma 2.1.0 不再保留现行补充材料。
未补齐的当前发布包逐项列在 [../REVIEW.md](../REVIEW.md)；退役组件的旧核验记录另存于 `../history/`。
