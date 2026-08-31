#!/bin/sh
set -eu

deploy_dir="${DEPLOY_DIR:-/opt/reven}"
operation="${DEPLOY_OPERATION:-deploy}"
image="${REVEN_IMAGE:-}"
env_file="$deploy_dir/.env"
infra_dir="$deploy_dir/infra"
compose_file="$infra_dir/compose/docker-compose.yml"
release_infra_path="/opt/reven-release/infra"
last_healthy_file="$deploy_dir/.last-healthy-image"
previous_healthy_file="$deploy_dir/.previous-healthy-image"
docker_config="$deploy_dir/.docker"
work_dir=""
export_container=""

die() {
  echo "$*" >&2
  exit 1
}

cleanup() {
  if [ -n "$export_container" ]; then
    DOCKER_CONFIG="$docker_config" docker rm "$export_container" >/dev/null 2>&1 || true
    export_container=""
  fi
  if [ -n "$work_dir" ] && [ "$work_dir" != "$deploy_dir" ] && [ -d "$work_dir" ]; then
    rm -rf "$work_dir"
    work_dir=""
  fi
}

trap cleanup 0
trap 'exit 1' HUP INT TERM

compose() {
  DOCKER_CONFIG="$docker_config" docker compose --env-file "$env_file" -f "$compose_file" "$@"
}

validate_image_reference() {
  validation_target="$1"
  validation_pattern='^registry\.cn-hangzhou\.aliyuncs\.com/wangyiyang/reven@sha256:[0-9a-f]{64}$'

  if ! printf '%s\n' "$validation_target" | grep -Eq "$validation_pattern"; then
    echo "REVEN_IMAGE must be registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven@sha256:<64 lowercase hex>" >&2
    return 1
  fi
}

read_configured_image() {
  awk -F= '$1 == "REVEN_IMAGE" { print substr($0, length($1) + 2); exit }' "$env_file"
}

write_configured_image() {
  config_target="$1"
  temporary_file="$(mktemp "$env_file.XXXXXX")" || return 1
  if ! awk -v image="$config_target" '
    BEGIN { replaced = 0 }
    $0 ~ /^REVEN_IMAGE=/ { print "REVEN_IMAGE=" image; replaced = 1; next }
    { print }
    END { if (!replaced) print "REVEN_IMAGE=" image }
  ' "$env_file" >"$temporary_file"; then
    rm -f "$temporary_file"
    return 1
  fi
  if ! chmod 600 "$temporary_file"; then
    rm -f "$temporary_file"
    return 1
  fi
  if ! mv "$temporary_file" "$env_file"; then
    rm -f "$temporary_file"
    return 1
  fi
}

remove_configured_image() {
  temporary_file="$(mktemp "$env_file.XXXXXX")" || return 1
  if ! awk '$0 !~ /^REVEN_IMAGE=/' "$env_file" >"$temporary_file"; then
    rm -f "$temporary_file"
    return 1
  fi
  if ! chmod 600 "$temporary_file"; then
    rm -f "$temporary_file"
    return 1
  fi
  if ! mv "$temporary_file" "$env_file"; then
    rm -f "$temporary_file"
    return 1
  fi
}

validate_and_pull() {
  validation_target="$1"
  validate_image_reference "$validation_target" || return 1
  DOCKER_CONFIG="$docker_config" docker pull "$validation_target" || return 1
  actual_image="$(DOCKER_CONFIG="$docker_config" docker image inspect "$validation_target" --format '{{index .RepoDigests 0}}')" || return 1
  if [ "$actual_image" != "$validation_target" ]; then
    echo "Pulled image digest does not match deployment target" >&2
    return 1
  fi
}

extract_release_infra() {
  extraction_target="$1"
  extraction_destination="$2"

  mkdir -p "$extraction_destination" || return 1
  export_container="$(DOCKER_CONFIG="$docker_config" docker create "$extraction_target")" || return 1
  DOCKER_CONFIG="$docker_config" docker cp \
    "$export_container:$release_infra_path/." "$extraction_destination/" || return 1
  DOCKER_CONFIG="$docker_config" docker rm "$export_container" >/dev/null || return 1
  export_container=""
}

validate_release_infra() {
  validation_source="$1"
  unexpected_paths_file="$2"

  for required_path in \
    compose/docker-compose.yml \
    caddy/Caddyfile \
    docker/seccomp-bwrap.json
  do
    if [ ! -f "$validation_source/$required_path" ] || [ -L "$validation_source/$required_path" ]; then
      echo "Release image is missing required infra file: $required_path" >&2
      return 1
    fi
  done

  find "$validation_source" ! -type d ! -type f -print >"$unexpected_paths_file" || return 1
  if [ -s "$unexpected_paths_file" ]; then
    echo "Release image infra contains unsupported file types" >&2
    return 1
  fi
}

sync_infra() {
  sync_source="$1"
  sync_destination="$2"
  sync_paths_file="$work_dir/sync-paths"

  [ -d "$sync_source" ] || return 1
  if [ -L "$sync_destination" ] || { [ -e "$sync_destination" ] && [ ! -d "$sync_destination" ]; }; then
    echo "Deployment infra path must be a directory: $sync_destination" >&2
    return 1
  fi
  mkdir -p "$sync_destination" || return 1
  find "$sync_destination" -depth ! -path "$sync_destination" -print >"$sync_paths_file" || return 1

  while IFS= read -r active_path; do
    relative_path=${active_path#"$sync_destination"/}
    staged_path="$sync_source/$relative_path"

    if [ -L "$active_path" ]; then
      rm -f "$active_path" || return 1
    elif [ -d "$active_path" ]; then
      if [ ! -d "$staged_path" ] || [ -L "$staged_path" ]; then
        rmdir "$active_path" || return 1
      fi
    elif [ -f "$active_path" ]; then
      if [ ! -f "$staged_path" ] || [ -L "$staged_path" ]; then
        rm -f "$active_path" || return 1
      fi
    else
      rm -f "$active_path" || return 1
    fi
  done <"$sync_paths_file"

  # cp overwrites existing regular files in place, preserving Caddy's bind-mount inode,
  # while -a also applies release ownership, modes, and timestamps.
  cp -a "$sync_source/." "$sync_destination/" || return 1
}

start_and_check_health() {
  compose pull reven || return 1
  compose up -d --wait --no-build || return 1
  compose exec -T reven python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).read()" || return 1
}

reload_caddy() {
  if compose ps --status running -q caddy | grep -q .; then
    compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
  else
    # Caddy 未运行（典型：Reven 健康检查失败，depends_on 阻止 Caddy 启动）。
    # 用 --no-deps 绕过 depends_on，以恢复后的旧 Caddyfile 尽力拉起：
    # 静态页可恢复访问，API 是否可用取决于 Reven 容器自身状态。
    compose up -d --no-deps --no-build caddy
  fi
}

activate_target() {
  activation_source="$1"
  activation_target="$2"
  activation_caddy_changed="$3"

  sync_infra "$activation_source" "$infra_dir" || return 1
  write_configured_image "$activation_target" || return 1
  start_and_check_health || return 1
  if [ "$activation_caddy_changed" = true ]; then
    reload_caddy || return 1
  fi
}

restore_previous_state() {
  restore_source="$1"
  restore_image="$2"
  restore_caddy_changed="$3"
  restore_failed=0

  sync_infra "$restore_source" "$infra_dir" || restore_failed=1
  if [ -n "$restore_image" ]; then
    write_configured_image "$restore_image" || restore_failed=1
  else
    remove_configured_image || restore_failed=1
  fi

  # Do not restart an older Reven image: the failed target may already have migrated the database.
  if [ "$restore_failed" -eq 0 ] && [ "$restore_caddy_changed" = true ] \
    && [ -f "$restore_source/caddy/Caddyfile" ]; then
    reload_caddy || restore_failed=1
  fi
  [ "$restore_failed" -eq 0 ]
}

deploy_image() {
  deployment_target="$1"
  prior_image="$(read_configured_image || true)"
  if [ -n "$prior_image" ]; then
    validate_image_reference "$prior_image" || die "Existing REVEN_IMAGE configuration is invalid"
  fi
  validate_and_pull "$deployment_target" || die "Unable to prepare deployment image"

  work_dir="$(mktemp -d "$deploy_dir/.deploy.XXXXXX")" || die "Unable to create deployment workspace"
  staged_infra="$work_dir/release-infra"
  backup_infra="$work_dir/infra-backup"
  extract_release_infra "$deployment_target" "$staged_infra" || die "Unable to export infra from deployment image"
  validate_release_infra "$staged_infra" "$work_dir/unexpected-infra-paths" || die "Deployment image infra is invalid"

  mkdir -p "$backup_infra" || die "Unable to create infra backup"
  if [ -L "$infra_dir" ] || { [ -e "$infra_dir" ] && [ ! -d "$infra_dir" ]; }; then
    die "Deployment infra path must be a directory: $infra_dir"
  fi
  if [ -d "$infra_dir" ]; then
    cp -a "$infra_dir/." "$backup_infra/" || die "Unable to back up deployment infra"
  fi
  if cmp -s "$staged_infra/caddy/Caddyfile" "$infra_dir/caddy/Caddyfile"; then
    caddy_changed=false
  else
    caddy_changed=true
  fi

  if ! activate_target "$staged_infra" "$deployment_target" "$caddy_changed"; then
    if restore_previous_state "$backup_infra" "$prior_image" "$caddy_changed"; then
      die "Deployment failed; restored REVEN_IMAGE and infra without starting an older app image or downgrading the database"
    fi
    die "Deployment failed and automatic restoration was incomplete; inspect REVEN_IMAGE, infra, and Caddy immediately"
  fi

  if [ -n "$prior_image" ] && [ "$prior_image" != "$deployment_target" ]; then
    printf '%s\n' "$prior_image" >"$previous_healthy_file"
  fi
  printf '%s\n' "$deployment_target" >"$last_healthy_file"
}

test -f "$env_file" || die "Missing deployment environment file: $env_file"
test -d "$docker_config" || die "Missing Docker credential directory: $docker_config"

case "$operation" in
  deploy)
    [ -n "$image" ] || die "REVEN_IMAGE is required for deploy"
    deploy_image "$image"
    ;;
  rollback)
    rollback_target="$(cat "$previous_healthy_file" 2>/dev/null || true)"
    [ -n "$rollback_target" ] || die "No previous healthy image is recorded for rollback"
    deploy_image "$rollback_target"
    ;;
  *) die "DEPLOY_OPERATION must be deploy or rollback" ;;
esac
