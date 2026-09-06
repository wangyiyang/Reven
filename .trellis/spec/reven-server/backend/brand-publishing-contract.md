# Brand Publishing Contract

## Scenario: Change brand profiles, channel templates, or template application in the delivery pipeline

### 1. Scope / Trigger

Use this contract whenever a change touches `reven/brand/`, brand binding on
`publication_jobs`, WeChat/blog template application, footer assets, renderer
theme parameters, or the Notion VI Hub migration. Brand configuration is an
**input parameter** to publishing, never a mutation of article content.

### 2. Signatures

- Domain: `reven.brand.application` (pure functions), `reven.brand.service`,
  `reven.brand.repository`, `reven.brand.migration`.
- Resolution: `resolve_brand_config(session) -> ResolvedBrand | None`;
  `None` means legacy behavior everywhere (AC9).
- Template application: `apply_wechat_template(markdown, brand_payload,
  template_payload, assets_by_id, *, embedded_sha256) -> (markdown, warnings)`;
  shared verbatim by preview and delivery.
- Freeze: `reven.jobs.brand_preparation.prepare_brand` runs at job creation;
  `jobs/service.py` persists `metadata["brand"]`, `metadata["blog_fields"]`,
  `metadata["footer_assets"]` and the three version FKs.
- Delivery: `reven.publishing.wechat.brand.apply_brand_for_delivery`,
  `BlogConverter` frontmatter extras via `BlogBrandFields`.
- API: `/api/brand/profile|assets|templates/{channel}|import/*` and
  `POST /api/articles/{id}/jobs` (regenerate) / `POST /api/articles/{id}/cover`.
- Database: `brand_versions`, `channel_template_versions`, `brand_assets`,
  `brand_import_runs`; `publication_jobs` gains `brand_version_id`,
  `wechat_template_version_id`, `blog_template_version_id`, `brand_binding_key`.

### 3. Contracts

- Version rows are immutable once published. Editing copies the published row
  into the single allowed draft; publishing the draft archives the old
  published row. Partial unique indexes guarantee at most one draft and one
  published per scope (brand, or per channel template).
- Freeze happens at job creation: the three FKs (`ON DELETE RESTRICT`) plus
  `brand_binding_key = sha256(f"{brand_id}:{wechat_id}:{blog_id}")` are
  written once and never updated. Retry reuses the frozen row; "regenerate
  with current config" creates a new job under a different binding key — these
  two semantics must stay distinct. The idempotency constraint is
  `(article_id, content_hash, target_channels_hash, brand_binding_key)`.
- Legacy fallback is load-bearing: no published brand profile means
  `binding_key='legacy'`, no template application, no blog frontmatter extras,
  author falls back to the WeChat integration `public_config.author`, and
  renderer output is byte-identical to the pre-brand behavior.
- Channel artifacts never write back to the article body. Footer modules and
  author/digest overrides exist only in the rendered WeChat draft or blog
  frontmatter; snapshots and Notion remain untouched. Dedup ambiguity
  (`footer_conflict_uncertain`) must only warn, never modify content.
- Footer image assets are materialized during preparation (same staging as
  body images) and referenced in delivery as continuation placeholders
  `reven-asset://image/{N+k}` with sha256 verification against
  `metadata["footer_assets"]`. A missing frozen file is a
  `BlockedPublishError`; do not re-download external URLs at delivery.
- Renderer theme parameters are optional and validated in Python
  (`WechatTheme` / `theme_from_params`) before entering the subprocess;
  omitting them must keep renderer output byte-identical.
- Author precedence is brand `default_author` > WeChat integration
  `public_config.author` > Notion. Both preparation status and delivery
  context follow this order.
- Validation stays two-tier (`errors` block, `warnings` inform). Subjective
  style judgments never produce errors.
- Notion migration produces drafts only, never publishes. It is idempotent
  per `notion_page_id`, dedupes assets by sha256, never overwrites an existing
  draft, and records unimportable items in `report.skipped` with reasons.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| No published brand profile | Legacy behavior; warning `brand_not_configured` |
| Job has `brand_binding_key='legacy'` | No template application, no blog extras, byte-identical renderer output |
| Footer asset frozen at preparation is missing/disabled at delivery | `BlockedPublishError` (`brand_config_missing` / asset unreadable) |
| Footer module already present in body (sha256 or text fingerprint) | Skip append, warning `footer_already_present` |
| Dedup uncertain | Warning `footer_conflict_uncertain`; body unchanged |
| Second publish of same draft | New version number; old published row archived |
| Regenerate with same content and same binding | Reuse the existing waiting/frozen job (idempotent) |
| Regenerate with same content and new binding | New frozen job; old job kept as history |
| VI Hub import repeated after success | Return the existing run; no new draft/assets |
| VI Hub import with existing draft | Draft untouched; report `skipped_existing_draft` |
| COS or Notion integration unconfigured | Explicit 503 `cos_not_configured` / 409 `notion_not_configured` |

### 5. Good / Base / Bad Cases

- Good: user publishes a brand profile and both channel templates; the next
  job freezes them, WeChat draft carries footer modules as frozen local
  placeholders, and the blog frontmatter gains `cover`/`og_image_url`/`author`.
- Base: brand never configured; every article publishes exactly as before,
  with a non-blocking `brand_not_configured` hint.
- Bad: mutating a published version row in place, appending footer modules
  back into the snapshot, re-downloading footer images from external URLs at
  delivery, or publishing migration output automatically — all forbidden.

### 6. Tests Required

- Pure-function tests for `apply_wechat_template` dedup three-state
  (append / skip / uncertain) with caller-supplied `embedded_sha256`.
- Freeze tests: metadata and FKs written once; retry keeps frozen values;
  regenerate creates a distinct binding key.
- Legacy regression: job without binding renders byte-identical output and
  writes no blog extras.
- Renderer: theme passthrough plus byte-identical default regression.
- Migration: dry-run writes nothing, execute is idempotent, existing draft
  preserved, failure run stores a redacted `error`.
- Migration DB tests must assert the final head revision stays in sync with
  `FINAL_REVISION` in `test_merge_heads_migration.py`.

### 7. Wrong vs Correct

#### Wrong

```python
# 交付时从公网下载文末二维码并直接把外链塞进 markdown
markdown += f"\n\n![二维码]({asset.public_url})\n"
```

External URLs bypass the frozen-asset security invariant
(`validate_placeholders` rejects them) and break preview/delivery parity.

#### Correct

```python
# 准备阶段随正文一并物化；交付时按续序占位符引用并校验 sha256
markdown, entries = apply_brand_for_delivery(markdown, brand_meta, footer_assets)
# entries -> reven-asset://image/{N+k}，文件来自同一 staging 目录
```
