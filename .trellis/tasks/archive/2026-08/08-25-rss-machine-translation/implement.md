# Implementation Plan: 百度/阿里 RSS 机翻

## 1. 移除腾讯翻译并收紧 API 边界

- 删除腾讯翻译后端 schema、连接测试注册/适配器、客户端及关联导出。
- 将支持 provider 收敛为百度、阿里；所有 provider 路由对 `translate_tencent` 验证为 404。
- 在集成列表响应处过滤不受支持的旧 provider，避免未知行破坏前端解析。
- 新增 `0015_remove_tencent_translation` 精确迁移：接在 `0014_merge_crm_and_integration` 后，只删除 `translate_tencent` 行；downgrade 明确 no-op。
- 删除 CMS 腾讯类型、配置卡、健康状态分支、测试 fixture/断言，保留百度/阿里交互。
- 先补回归测试，再完成移除；重点覆盖迁移精确性、404 与列表防御过滤。

## 2. 实现百度/阿里运行时配置加载器

- 建立共享支持 provider 定义和 typed runtime binding。
- 通过现有 repository/secret 解密能力加载 enabled 且凭证完整的百度/阿里配置。
- 按 priority 升序、同级百度 → 阿里排序；错误诊断禁止泄露 secret。
- 单测覆盖禁用、字段缺失、解密失败、排序与资源关闭。

## 3. 实现 RSS 机翻编排器

- 定义 `TextTranslator` 协议及百度/阿里适配器。
- 实现不超过 1,000 字符的确定性分段、顺序重组、空摘要跳过和 2,000/6,000 输出边界。
- 实现百度 1 QPS limiter，时钟与 sleep 可注入。
- 实现 provider 故障切换：字段失败则当前条目完整重试，并在本次调用后续条目中停用故障 provider。
- 单测覆盖成功短路、各种错误、部分字段失败、后续条目隔离、分段与限流。

## 4. 接入 RSS factory 与 Qwen 最终兜底

- 在 RSS factory 用数据库配置构建百度/阿里链，并将现有 Qwen localizer 作为最终 fallback。
- 无机翻配置与全部机翻失败时走 Qwen；机翻成功时不调用 Qwen。
- 保留 `PartialLocalizationError`、原文回退、translation degraded 与 `RSS_MODEL_REVIEW_ENABLED` 行为。
- 补 factory/discovery 回归测试，确认资源生命周期和现有筛选复核不变。

## 5. 文档、跨层检查与验证

- 更新必要的集成配置/API 文档，说明仅支持百度/阿里、优先级、1 QPS 与不可逆腾讯凭证清理。
- 搜索并清除非历史文档中的 `translate_tencent`/腾讯翻译运行时代码引用。
- 运行以下验证：

```bash
uv run ruff check server
uv run ruff format --check server
uv run mypy server/src
uv run alembic -c server/migrations/alembic.ini upgrade head
uv run pytest server/tests --cov=reven --cov-report=term-missing --cov-fail-under=80
pnpm --filter @reven/web lint
pnpm --filter @reven/web exec tsc --noEmit
pnpm --filter @reven/web test --run
pnpm --filter @reven/web build
git diff --check
```

## Delivery Boundaries

- 不调用真实生产翻译服务，不读取或输出真实凭证。
- 数据迁移会永久删除腾讯翻译密文；只有用户批准本计划后才进入实现。
- 实现完成后提交分支、创建 PR，并报告本地验证结果；CI 由外部流水线继续运行。
