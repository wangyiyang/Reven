# Sync production infra from release image

## Goal

Make every production deploy use the `infra/` files embedded in the exact
immutable Reven image being deployed, eliminating drift in the manually
managed `/opt/reven/infra` snapshot.

## Requirements

- The production image contains the deployable `infra/` tree as release data.
- Both normal deploys and rollbacks extract `infra/` from their target image
  before starting services.
- Synchronization preserves host-only state such as `.env`, Docker credentials,
  image history files, and deployment scripts.
- A changed Caddyfile is loaded into the running Caddy service during the same
  deployment.
- A failed deployment restores the previously configured image and infra files.
- CI exercises the image export contract and the deployment synchronization
  behavior without touching a real production host.

## Acceptance Criteria

- [x] The built image exposes its release infra at a stable documented path.
- [x] `scripts/deploy_reven.sh` exports and validates infra from the target image.
- [x] Removed release infra files do not linger under `/opt/reven/infra`.
- [x] Caddy reload occurs only when its config content changed.
- [x] Rollback selects and synchronizes infra from the rollback image.
- [x] Automated tests cover success, unchanged/changed Caddy config, and failure
      restoration paths.

## Constraints

- The deploy host is not a Git checkout and must not depend on repository files
  beyond the restricted deployment script copied by the release workflow.
- Deployment continues to accept digest-pinned Alibaba ACR images only.
- The script remains POSIX `sh` compatible and uses tools already required on
  the Docker host.
