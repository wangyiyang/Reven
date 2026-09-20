# Integration Provider Contract

## Scenario: Add, change, or retire an integration provider

### 1. Scope / Trigger

Use this contract whenever a change alters a provider identifier, credential schema, persisted integration row, connection-test adapter, runtime consumer, or CMS card. A provider is a cross-layer contract: changing only one surface can make `GET /api/integrations` unparsable by the CMS or leave retired encrypted credentials active in the database.

### 2. Signatures

- Canonical registry: `reven.integrations.providers.SUPPORTED_INTEGRATION_PROVIDERS`.
- Translation subset and stable tie order: `reven.integrations.providers.TRANSLATION_PROVIDERS`.
- API:
  - `GET /api/integrations -> list[IntegrationResponse]`
  - `GET /api/integrations/{provider} -> IntegrationResponse | 404`
  - `PUT /api/integrations/{provider} -> IntegrationResponse | 404 | 422`
  - `DELETE /api/integrations/{provider}/secret -> IntegrationResponse | 404`
  - `POST /api/integrations/{provider}/test -> IntegrationResponse | 404`
- Database owner: `integrations.provider` is unique; `public_config` is JSONB and `encrypted_secret` is nullable ciphertext.
- RSS translation loader: `load_translation_configs(session_factory) -> tuple[TranslationConfig, ...]`.

### 3. Contracts

- The backend registry is the source of truth for API provider membership and list filtering. Unknown persisted rows must never cross the API boundary.
- Adding or removing a provider requires auditing all mirrored surfaces: canonical registry, Pydantic request model and `PUT_MODELS`, secret-hint field, connection-test registration/client, CMS `Provider` union/runtime guard/card, and tests.
- API responses expose only `secret_configured` and an irreversible `secret_hint`; plaintext and ciphertext never appear in responses, logs, exception messages, dataclass `repr`, or snapshots.
- Runtime loaders use only enabled rows with complete, decryptable credentials. They may skip unusable rows with a log containing provider and error type only.
- Translation configs sort by numeric `priority`, then the order declared in `TRANSLATION_PROVIDERS`.
- Retiring a credential-bearing provider requires an exact data migration. If credentials are deleted, downgrade must not create a misleading empty row or pretend the secret is recoverable; document the irreversible operation in release-facing docs.
- The CMS `Provider` union and runtime type guard must contain the same supported values returned by the backend.

### 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Path provider is not in the canonical registry | `404 INTEGRATION_PROVIDER_UNKNOWN` before body parsing or adapter lookup |
| Known provider request body violates its strict schema | HTTP 422; extra fields remain forbidden |
| Credential-bearing dataclass fields | Must use `field(repr=False)` (precedent: `integrations/translation/configuration.py`), with a test asserting repr contains no credentials |
| Unsupported legacy row exists in `integrations` | Omit it from list responses; keep supported rows visible |
| Enabled runtime row has no ciphertext or incomplete fields | Skip it; do not fail application startup or the RSS run |
| Ciphertext cannot be decrypted | Skip it and log only provider plus error type |
| Provider returns an empty or whitespace-only translation | Treat as invalid response and fail over atomically |
| Retired provider migration is downgraded | Do not restore fabricated credentials or an unusable placeholder row |

### 5. Good / Base / Bad Cases

- Good: Baidu and Aliyun rows are enabled with complete secrets; the loader returns them by priority with a stable tie order and no secret-bearing representation.
- Base: no usable machine-translation row exists; RSS uses the existing Qwen fallback and the settings page still loads all other integrations.
- Bad: a legacy `translate_tencent` row remains after a partial rollout; the API filters it, provider-specific routes return 404, and its ciphertext is never serialized.

### 6. Tests Required

- API regression: every route for a retired provider returns `INTEGRATION_PROVIDER_UNKNOWN`; list filtering hides an unknown row while preserving at least one valid provider and redacting both secrets.
- Migration regression on PostgreSQL: seed the retired row, a surviving translation row, and an unrelated provider; upgrade deletes exactly the retired row, and downgrade does not recreate it.
- Loader tests: disabled, missing-secret, incomplete-secret, and corrupt-secret rows are skipped; numeric priority and equal-priority tie order are separate assertions; `repr` and captured logs contain no credentials.
- Frontend tests: retired cards are absent, supported cards still serialize typed public config, and the full integration response guard accepts only the backend-supported set.
- Runtime tests: invalid/whitespace output triggers whole-entry retry, a failed provider is disabled for later entries, and final fallback preserves partial results.

### 7. Wrong vs Correct

#### Wrong

```python
# Removing only the UI card leaves an active backend route and a legacy row that
# can make the frontend reject the entire list response.
PROVIDERS = (*PROVIDERS, "retired_provider")
```

#### Correct

```python
# One backend registry owns membership; API list responses filter repository
# rows through it, and retirement includes an exact credential-purge migration.
SUPPORTED_INTEGRATION_PROVIDERS = (
    "notion",
    "github",
    "wechat",
    "feishu",
    "feishu_bot",
    *TRANSLATION_PROVIDERS,
    "embedding",
)
```
