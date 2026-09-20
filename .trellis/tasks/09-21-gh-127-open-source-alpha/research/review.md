# #127 实施审查（2026-09-21）

## 结论

已审查应用 Origin/CSRF/会话、自托管 Compose/Caddy、原生产兼容、构建上下文保护、许可采集与文档。
本轮可直接处理的问题已修复并通过针对检查；真实部署、外部服务和分发许可门槛仍按各自验收记录判断，不能因代码审查通过而关闭 #127。

## 已修复

1. `server/src/reven/security/origin.py` 原先通过 Python IDNA2003 将 `https://faß.de` 改为 `https://fass.de`，与浏览器的 `https://xn--fa-hia.de` 不一致。按主会话确认，改为只接受 ASCII authority/Punycode，保留 IPv6 和端口行为；配置错误及自托管文档同步说明。回归先得到两项失败，再确认修正通过，额外覆盖会被小写转换的 Unicode Kelvin 字符。
2. `.github/workflows/ci.yml` 的 backend 路径过滤未覆盖新的自托管配置及烟测脚本。补充 `infra/self-host/**`、Dockerfile 专属 ignore 和 `scripts/self_host*.py`；新增回归验证这些路径会选中 backend，同时 container 仍仅由 `inputs.full` 开启。
3. `CONTRIBUTING.md` 只安装 Python 3.12 后运行无版本约束的 uv sync，实测仍可能选已有 3.13。同步主会话实际成功的 `--python 3.12` 命令，并说明手动完整 CI 无生产发布副作用。
4. 新跨层约定尚未持久化。按 `trellis-update-spec` 新增七段 `open-source-self-host-contract.md` 及索引；CI 规范与手动入口、自托管验证顺序、路径过滤保持一致。

## 未修复及验收边界

- 预存低优先级边界：配置 `https://127.1` 或 `https://0177.0.0.1` 会保留该 ASCII host，浏览器将其规范化为 `127.0.0.1` 后 Origin 不一致。指南使用标准 DNS/localhost，不受影响；本轮未扩大既有数字地址兼容语义，建议另行明确仅接受标准四段十进制 IPv4。
- 许可采集与补充材料仍由许可代理根据最终镜像继续核对；源码中已显式保留缺原文/内嵌二进制/对应源码义务等未完成项。采集脚本不是许可合规结论。
- 历史第三方 Token、Actions 附属材料与私密报告入口状态以 `security-audit.md` 为准。没有改写历史、测试 Token 或改变仓库可见性。
- 原生 Linux AMD64 默认 Compose 沙箱、备份恢复、可信 HTTPS 与真实 Notion 的最终结果由各自运行验收记录给出。本审查不将本机 ARM 仿真、结构测试或 Fake Notion 当作这些验收。

## 验证

- Ruff check / format：通过；最终检查覆盖 357 个 Python 文件。
- Mypy：通过，190 个源文件。
- Web ESLint：通过。
- Actionlint（变更的 CI 工作流）、`git diff --check`：通过。
- 配置/认证/CSRF：针对运行 79 项通过；之后新增 Kelvin 拒绝用例并调整 authority 原始字符校验，配置套件 34 项通过。
- 自托管配置、CI 自动化及烟测失败路径：23 项通过。
- 复用主会话此前完整后端结果：949 项通过、覆盖率 87.06%；前端测试/构建、renderer 39 项通过。审查未重复全量测试，新增及修正以针对检查补足。
- 对实际构建镜像只读探针确认 Python 3.12.13 拒绝非法 IPv6 authority 后缀；此探针在 ARM 宿主仿真运行，仅验证解析库行为。

没有提交或推送。许可与真实部署代理后续变更仍需在最终合并差异上核对相应结果。

## 原始许可文本的最终空白检查

许可材料提交后，针对基线 `7761675` 的完整差异检查发现三份上游原文带有缩进或行尾空白：Node LICENSE、Rollup 4.62.3 的 Darwin ARM64 LICENSE.md、minitest 5.27.0 README.rdoc。
为保持原文与证据 SHA-256 不变，在 `.gitattributes` 仅为这三个精确路径设置 `-whitespace`，并说明保留上游字节的原因；未扩展到其他许可或脚本。
再次运行 `git diff --check 7761675` 通过；三份原文与已提交版本逐字节一致，校验和未变。
许可采集器的最终结果由主会话与许可代理复核：4 项回归通过，Ruby 99 项中 98 项已有原文，rubyzip 的许可冲突仍明确保留。
