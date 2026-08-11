#!/bin/sh
set -eu

deploy_dir="${DEPLOY_DIR:-/opt/reven}"
operation="${DEPLOY_OPERATION:-deploy}"
image="${REVEN_IMAGE:-}"
env_file="$deploy_dir/.env"
compose_file="$deploy_dir/infra/compose/docker-compose.yml"
last_healthy_file="$deploy_dir/.last-healthy-image"
previous_healthy_file="$deploy_dir/.previous-healthy-image"
docker_config="$deploy_dir/.docker"

die() {
  echo "$*" >&2
  exit 1
}

compose() {
  DOCKER_CONFIG="$docker_config" docker compose --env-file "$env_file" -f "$compose_file" "$@"
}

read_configured_image() {
  awk -F= '$1 == "REVEN_IMAGE" { print substr($0, length($1) + 2); exit }' "$env_file"
}

write_configured_image() {
  target="$1"
  temporary_file="$(mktemp "$env_file.XXXXXX")"
  awk -v image="$target" '
    BEGIN { replaced = 0 }
    $0 ~ /^REVEN_IMAGE=/ { print "REVEN_IMAGE=" image; replaced = 1; next }
    { print }
    END { if (!replaced) print "REVEN_IMAGE=" image }
  ' "$env_file" >"$temporary_file"
  chmod 600 "$temporary_file"
  mv "$temporary_file" "$env_file"
}

validate_and_pull() {
  target="$1"
  cd "$deploy_dir"
  REVEN_IMAGE="$target" ./scripts/validate_reven_image.sh
  DOCKER_CONFIG="$docker_config" docker pull "$target"
  actual_image="$(docker image inspect "$target" --format '{{index .RepoDigests 0}}')"
  [ "$actual_image" = "$target" ] || die "Pulled image digest does not match deployment target"
}

start_and_check_health() {
  compose pull reven
  compose up -d --wait --no-build
  compose exec -T reven python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).read()"
}

deploy_image() {
  target="$1"
  prior_image="$(read_configured_image || true)"
  validate_and_pull "$target"
  write_configured_image "$target"
  if ! start_and_check_health; then
    if [ -n "$prior_image" ]; then
      write_configured_image "$prior_image"
    fi
    die "Deployment failed; restored REVEN_IMAGE configuration without database downgrade"
  fi
  if [ -n "$prior_image" ] && [ "$prior_image" != "$target" ]; then
    printf '%s\n' "$prior_image" >"$previous_healthy_file"
  fi
  printf '%s\n' "$target" >"$last_healthy_file"
}

test -f "$env_file" || die "Missing deployment environment file: $env_file"
test -f "$compose_file" || die "Missing Compose file: $compose_file"
test -d "$docker_config" || die "Missing Docker credential directory: $docker_config"

case "$operation" in
  deploy)
    [ -n "$image" ] || die "REVEN_IMAGE is required for deploy"
    deploy_image "$image"
    ;;
  rollback)
    target="$(cat "$previous_healthy_file" 2>/dev/null || true)"
    [ -n "$target" ] || die "No previous healthy image is recorded for rollback"
    deploy_image "$target"
    ;;
  *) die "DEPLOY_OPERATION must be deploy or rollback" ;;
esac
