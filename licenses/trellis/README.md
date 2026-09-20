# Trellis 工具来源与修改声明

Trellis 工具及其模板沿用上游 AGPL 授权，**不适用 Reven 根目录的 Apache-2.0 许可**。
本目录原样保留 [Trellis v0.6.15 LICENSE](https://github.com/mindfold-ai/Trellis/blob/v0.6.15/LICENSE)
和 [COPYRIGHT](https://github.com/mindfold-ai/Trellis/blob/v0.6.15/COPYRIGHT)，版权为 2026 Mindfold LLC。

上游 COPYRIGHT 使用“版本 3 或后续版本”，同版 CLI package.json 标注 `AGPL-3.0-only`。
这里保留两者差异，不自行重写上游许可或推定模板享有授权例外。

## 范围与修改

[FILES.tsv](FILES.tsv) 列出 `.trellis/.template-hashes.json` 管理的全部 213 个现存模板路径，
覆盖 `.trellis`、`.agents`、`.claude`、`.cursor`、`.codex`、`.dsh`、`.pi` 和 `.kimi-code`。
它不把项目自行编写的 tasks、workspace 日志、业务 spec 一概认定为 Trellis 代码。

以 2026-09-21 的核对结果为准：

- 172 个文件与固定上游版本中的模板逐字节相同（`verbatim`）。表中链接到内容相同的上游模板，可能被多个平台共用。
- 40 个文件包含平台生成适配（`generated-adaptation`），与已安装模板的 hash 相同。表中记录对应公共命令、技能或平台配置的来源路径；生成差异尚未逐行人工复核。
- `.trellis/config.yaml` 与上游及已安装模板均不同（`locally-modified`）：Reven 配置了自动检测的 monorepo 包路径及 `default_package: @reven/web`。修改日期见该行的 `last_commit_date`；本地适配继续按上游 AGPL 许可提供。
- 本表保存上游原文、安装基线、当前文件三个 SHA-256 以及最后提交日期。后续修改这些工具时，应同步修改声明、日期和清单；不得以根许可证覆盖工具改动。

对应修改后的完整工具源码就在表中的仓库路径内。应用运行镜像不复制这些开发工具，
其独立作品与应用的具体边界见根目录 THIRD_PARTY_NOTICES.md。

## 复查方法

下载固定源码归档 `https://codeload.github.com/mindfold-ai/Trellis/tar.gz/refs/tags/v0.6.15`，
本次归档 SHA-256 为 `a608c924db40ccfcafec2a91b60c063ddca8ad922196d121ca0863e8d65d0ac8`。
在仓库根目录用 Python 3.12 执行：

```sh
python scripts/licenses/trellis-provenance.py /path/to/Trellis-v0.6.15.tar.gz
```

该命令不下载或执行上游代码；缺少记录文件或来源路径时会失败。
模板生成规则、上游授权表述差异和未列入 hash 清单的可能复制内容仍需发布前复核。
