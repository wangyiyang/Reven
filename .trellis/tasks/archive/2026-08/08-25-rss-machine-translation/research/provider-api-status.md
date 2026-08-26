# Translation provider API status (2026-08-25)

## Repository evidence

- `server/src/reven/rss/factory.py` still constructs `SiliconFlowChatClient` as the RSS `EntryLocalizer`.
- `server/src/reven/integrations/translation/tencent.py`, `baidu.py`, and `aliyun.py` contain single-text clients and connection-test adapters added by PR #85, but no RSS orchestration consumes them.
- `server/src/reven/api/schemas/integrations.py` already owns `priority` and `enabled`; provider credentials are encrypted in `integrations.encrypted_secret`.
- The current Tencent contract is TMT `TextTranslate` authenticated by SecretID/SecretKey and TC3-HMAC-SHA256.
- `server/src/reven/rss/ai.py` currently truncates titles to 2,000 characters and summaries to 6,000 characters before chat localization, and preserves completed batches through `PartialLocalizationError`.

## Current primary-source findings

### Tencent

- The [Tencent TMT API 3.0 change history](https://cloud.tencent.com/document/api/551/17231) records deletion of `TextTranslate` from the current API documentation on 2026-07-08. The current API overview no longer exposes a text-translation operation.
- Tencent's [partial-product retirement announcement](https://cloud.tencent.com/announce/detail/2274) directs text-translation users to TokenHub's Hy-MT2 family. This makes the issue's assumption that the legacy signed text API is a stable new integration unsafe without an explicit product decision.
- The current [TokenHub Hy-MT2 guide](https://cloud.tencent.com/document/product/1823/132252) exposes a mainland endpoint, `https://tokenhub.tencentmaas.com/v1/api/translations`, authenticated by Bearer API key. That credential and protocol are incompatible with the just-landed TMT SecretID/SecretKey schema.
- [TokenHub model pricing](https://cloud.tencent.com/document/product/1823/130055) lists Hy-MT2-Lite at 0.3 yuan/million input tokens and 1.2 yuan/million output tokens. The [new-user trial](https://cloud.tencent.com/document/product/1823/130053) currently gives language models one million trial tokens for one year, but this is a one-time promotional quota rather than the old TMT monthly character allowance.

### Baidu

- The [Baidu general translation product documentation](https://fanyi-api.baidu.com/product/113) confirms the existing MD5 signature and HTTPS endpoint, with Standard QPS=1. It recommends no more than 2,000 characters per request and documents up to 6,000 after authentication.
- The [Baidu onboarding guide](https://fanyi-api.baidu.com/doc/13) is stricter for the free Standard tier: one request per second and a 1,000-character single-request maximum. Runtime orchestration should therefore use the conservative 1,000-character limit unless the product adds an explicit service-tier setting.

### Alibaba Cloud

- The [Aliyun TranslateGeneral reference](https://api.aliyun.com/api/alimt/2018-10-12/TranslateGeneral) confirms the existing RPC operation and a 5,000-character maximum.
- The [Aliyun limits page](https://help.aliyun.com/zh/machine-translation/developer-reference/limits) documents 50 QPS for `TranslateGeneral` and fewer than 5,000 characters per request.

## Product decision and planning implications

1. The minimum common safe chunk size is 1,000 characters because the configured Baidu service tier is not persisted.
2. Baidu needs an explicit one-request-per-second limiter; merely executing entries sequentially still sends title and summary back-to-back.
3. A provider that fails during a run should be removed from the active chain for the remainder of that run to avoid repeatedly hitting a rate-limited or unavailable endpoint.
4. On 2026-08-25 the product owner chose to remove Tencent translation support and retain only Baidu and Alibaba Cloud. Implementation therefore removes both the legacy TMT contract and its configuration surfaces; it does not migrate to TokenHub.
5. Existing `translate_tencent` database rows contain encrypted credentials. An exact migration must delete those rows, with an explicit acknowledgement that downgrade cannot restore the secrets; the list API should also filter unknown provider rows as defense in depth.
6. Always-on LLM title polishing would undermine the stated resource-separation goal. The minimum compatible chat behavior is final fallback only, with model-based screening review kept independent.
