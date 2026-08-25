# Design

## Release contract

The runtime image stores the repository's deployable `infra/` tree at
`/opt/reven-release/infra`. The deploy script creates (but never starts) the
target image, copies that tree to a host-side staging directory, validates the
required Compose, Caddy, and seccomp files, then removes the temporary
container.

## Synchronization and activation

Infra is synchronized in place so the existing Caddyfile bind mount retains its
inode and sees updated content. New files are overlaid from staging, and paths
not present in staging are pruned. The host-only files live outside `infra/`
and are therefore untouched.

Before synchronization, the current infra tree is copied to a deployment-local
backup directory. If service startup or Caddy reload fails, the prior image is
written back to `.env` and the backup infra is restored in place. The script
does not restart the prior Reven image because the target may already have run
forward-only database migrations. Temporary containers and directories are
cleaned by a trap.

After `docker compose up`, Caddy is reloaded only when `cmp` detected a content
change in the staged Caddyfile. Compose changes are naturally applied by
`docker compose up`; the explicit reload handles the content-only Caddyfile
case.

## Verification

A shell integration harness supplies a fake `docker` executable and isolated
`DEPLOY_DIR`. It models image extraction, Compose calls, health checks, and
reload failure. CI also asserts that the production image contains the exact
release infra payload.
