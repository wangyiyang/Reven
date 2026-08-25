# Implementation Plan

1. [x] Copy `infra/` into a stable release-data path in the runtime image.
2. [x] Refactor the deploy script to extract, validate, back up, synchronize, and
   restore target-image infra with guaranteed temporary-resource cleanup.
3. [x] Reload Caddy only when its staged config differs from the active config.
4. [x] Add a fake-Docker integration test for deploy, no-op reload, rollback-source
   selection, stale-file pruning, and failed-activation restoration.
5. [x] Add the integration test and embedded-infra assertion to the container CI
   job.
6. [x] Run shell syntax checks, the integration harness, workflow parsing, and the
   relevant container validation available locally.

## Verification Notes

- POSIX shell syntax, five fake-Docker integration scenarios, focused pytest,
  Ruff, workflow YAML parsing, and `git diff --check` pass.
- A scratch image confirmed `COPY` plus `docker cp` exports an exact `infra/`
  payload.
- The full production build reached the unchanged pinned GHCR base-image lookup
  but was blocked twice by a registry TLS handshake timeout; CI retains the full
  build and exact exported-payload gate.
- No `.trellis/spec/` package scopes CI/operations. The durable deployment
  contract and pitfalls are recorded in `docs/runbook.md` and executable tests
  instead of creating a speculative package spec.
