# Agent 迁移后的许可核验记录（2026-10-06）

当前 Agent 改用 LangChain/LangGraph 与 psycopg，不再依赖 DeepSeek Harness SDK/runtime。迁移前完整记录保存在 [历史快照](history/before-agent-langgraph-20261006.md)，其中旧镜像 ID、锁文件哈希、Python 数量与 DSH 内嵌组件结论只适用于当时版本。

## 新增运行依赖

以下声明来自冻结安装的包 METADATA 与 dist-info 原文，不从包名猜测许可。版本由 uv.lock 固定；Dockerfile 继续为最终平台的实际 `--no-dev` 安装环境采集原文、来源与 SHA-256。

| 包 | 版本 | 声明许可 | 安装原文 |
| --- | --- | --- | --- |
| langchain | 1.4.3 | MIT | dist-info/licenses/LICENSE |
| langchain-core | 1.6.6 | MIT | dist-info/licenses/LICENSE |
| langchain-deepseek | 1.1.1 | MIT | dist-info/licenses/LICENSE |
| langchain-openai | 1.6.7 | MIT | dist-info/licenses/LICENSE |
| langgraph | 1.2.13 | MIT | dist-info/licenses/LICENSE |
| langgraph-checkpoint-postgres | 3.1.2 | MIT | dist-info/licenses/LICENSE |
| psycopg、psycopg-binary | 3.3.6 | LGPL-3.0-only | dist-info/licenses/LICENSE.txt |
| psycopg-pool | 3.3.3 | LGPL-3.0-only | dist-info/licenses/LICENSE.txt |

Agent 客户端与框架的其他传递依赖同样由实际安装清单采集，不能只保留上表的直接依赖。psycopg-binary 中 libpq/OpenSSL 等组件及其来源、许可义务按最终 Linux wheel 核对，本机 ARM64 包不能代替发布镜像证据。

## 保持的分发边界

原创代码 Apache-2.0、Trellis 原文及修改记录、三个 Fontsource OFL 原文、JS/Python/system 三类自动采集保持。当前依赖树、Web bundle 与最终镜像 SBOM 分别核对；JS 许可超集不代表这些包全部进入 bundle。旧 FastMCP 补充原文继续按名称和版本匹配，已退役依赖的历史记录不自动进入新清单。

前端锁文件未因 Agent 迁移修改，历史记录中的 JS 缺原文项与 Trellis 声明差异保留为待核实范围；本次没有重新宣称完成全部二进制分发审查。新增运行时也不能沿用旧 DSH 镜像的扫描结果。

## 验证方式

```bash
uv sync --frozen --all-packages --python 3.12
.venv/bin/python scripts/licenses/collect-runtime.py python /tmp/reven-agent-licenses licenses/supplemental/python
uv run pytest scripts/licenses/test_collectors.py
```

最终镜像必须继续检查 `/opt/reven-licenses` 三类清单及 evidence 哈希、Web 中的许可副本、SBOM 和既有固定严重漏洞门禁；不忽略缺原文或变更上游许可声明。实际执行证据记录在本次 Trellis 任务的 `research/implementation-evidence.md`。
