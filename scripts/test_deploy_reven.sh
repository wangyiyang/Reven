#!/bin/sh
set -eu

script_dir="$(CDPATH= cd "$(dirname "$0")" && pwd)"
deploy_script="$script_dir/deploy_reven.sh"
test_root="$(mktemp -d "${TMPDIR:-/tmp}/reven-deploy-test.XXXXXX")"
registry="registry.cn-hangzhou.aliyuncs.com/wangyiyang/reven"
image_a="$registry@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
image_b="$registry@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
image_c="$registry@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"

cleanup() {
  rm -rf "$test_root"
}
trap cleanup 0
trap 'exit 1' HUP INT TERM

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_equal() {
  expected="$1"
  actual="$2"
  description="$3"
  [ "$actual" = "$expected" ] || fail "$description (expected '$expected', got '$actual')"
}

assert_contains() {
  expected="$1"
  target_file="$2"
  grep -F "$expected" "$target_file" >/dev/null || fail "$target_file does not contain: $expected"
}

assert_not_contains() {
  unexpected="$1"
  target_file="$2"
  if grep -F "$unexpected" "$target_file" >/dev/null; then
    fail "$target_file unexpectedly contains: $unexpected"
  fi
}

make_infra() {
  fixture_root="$1"
  caddy_value="$2"
  compose_value="$3"
  marker_value="$4"

  mkdir -p "$fixture_root/caddy" "$fixture_root/compose" "$fixture_root/docker" "$fixture_root/nested"
  printf '%s\n' "$caddy_value" >"$fixture_root/caddy/Caddyfile"
  printf '%s\n' "$compose_value" >"$fixture_root/compose/docker-compose.yml"
  printf '%s\n' '{"defaultAction":"SCMP_ACT_ERRNO"}' >"$fixture_root/docker/seccomp-bwrap.json"
  printf '%s\n' "$marker_value" >"$fixture_root/nested/release-marker"
}

install_fake_docker() {
  fake_bin="$1"
  mkdir -p "$fake_bin"
  cp "$script_dir/testdata/fake_deploy_docker.sh" "$fake_bin/docker"
  chmod 755 "$fake_bin/docker"
}

setup_case() {
  case_name="$1"
  active_image="$2"
  case_root="$test_root/$case_name"
  host_root="$case_root/host"
  fake_root="$case_root/fake"
  fake_bin="$case_root/bin"

  mkdir -p "$host_root/.docker" "$host_root/scripts" "$fake_root/images" "$fake_root/containers"
  install_fake_docker "$fake_bin"
  make_infra "$fake_root/images/a/infra" 'caddy-a' 'compose-a' 'release-a'
  make_infra "$fake_root/images/b/infra" 'caddy-b' 'compose-b' 'release-b'
  make_infra "$fake_root/images/c/infra" 'caddy-b' 'compose-c' 'release-c'

  case "$active_image" in
    "$image_a") active_fixture="$fake_root/images/a/infra" ;;
    "$image_b") active_fixture="$fake_root/images/b/infra" ;;
    "$image_c") active_fixture="$fake_root/images/c/infra" ;;
    *) fail "unknown active image: $active_image" ;;
  esac
  mkdir -p "$host_root/infra"
  cp -R "$active_fixture/." "$host_root/infra/"
  printf 'APP_SECRET=preserved\nREVEN_IMAGE=%s\n' "$active_image" >"$host_root/.env"
  printf '%s\n' 'docker credentials' >"$host_root/.docker/config.json"
  printf '%s\n' 'host deployment helper' >"$host_root/scripts/local-helper"
  printf '%s\n' "$active_image" >"$host_root/.last-healthy-image"
  : >"$fake_root/docker.log"
  cp "$host_root/infra/caddy/Caddyfile" "$fake_root/loaded-caddy"
}

run_deploy() {
  deploy_operation="$1"
  deploy_image="$2"
  health_failure="$3"
  reload_failure_once="$4"

  PATH="$fake_bin:$PATH" \
    DEPLOY_DIR="$host_root" \
    DEPLOY_OPERATION="$deploy_operation" \
    REVEN_IMAGE="$deploy_image" \
    FAKE_DEPLOY_DIR="$host_root" \
    FAKE_DOCKER_ROOT="$fake_root" \
    FAKE_HEALTH_FAIL="$health_failure" \
    FAKE_RELOAD_FAIL_ONCE="$reload_failure_once" \
    sh "$deploy_script"
}

assert_no_temporary_resources() {
  temporary_paths="$(find "$host_root" -maxdepth 1 -name '.deploy.*' -print)"
  [ -z "$temporary_paths" ] || fail "temporary deployment directories were not removed"
  container_files="$(find "$fake_root/containers" -type f -print)"
  [ -z "$container_files" ] || fail "temporary export containers were not removed"
}

test_changed_caddy_success() {
  setup_case changed-success "$image_b"
  printf '%s\n' 'stale' >"$host_root/infra/stale-release-file"
  chmod 755 "$fake_root/images/a/infra/caddy/Caddyfile"
  chmod 600 "$host_root/infra/caddy/Caddyfile"
  caddy_inode_before="$(ls -di "$host_root/infra/caddy/Caddyfile" | awk '{print $1}')"

  run_deploy deploy "$image_a" 0 0

  assert_equal "$image_a" "$(awk -F= '$1 == "REVEN_IMAGE" { print substr($0, length($1) + 2) }' "$host_root/.env")" \
    'successful deploy configures the target image'
  assert_contains 'APP_SECRET=preserved' "$host_root/.env"
  diff -r "$fake_root/images/a/infra" "$host_root/infra" >/dev/null || fail 'target infra was not synchronized exactly'
  [ ! -e "$host_root/infra/stale-release-file" ] || fail 'stale release infra file was not pruned'
  assert_equal "$caddy_inode_before" "$(ls -di "$host_root/infra/caddy/Caddyfile" | awk '{print $1}')" \
    'Caddyfile inode changed during in-place synchronization'
  [ -x "$host_root/infra/caddy/Caddyfile" ] || fail 'target Caddyfile mode was not synchronized'
  assert_equal '1' "$(cat "$fake_root/reload-count")" 'changed Caddyfile should reload once'
  assert_equal 'caddy-a' "$(cat "$fake_root/loaded-caddy")" 'Caddy loaded the target config'
  assert_equal "$image_b" "$(cat "$host_root/.previous-healthy-image")" 'previous healthy image was recorded'
  assert_equal "$image_a" "$(cat "$host_root/.last-healthy-image")" 'last healthy image was recorded'
  assert_equal 'docker credentials' "$(cat "$host_root/.docker/config.json")" 'Docker credentials changed'
  assert_equal 'host deployment helper' "$(cat "$host_root/scripts/local-helper")" 'host script changed'
  assert_contains 'fake-container:/opt/reven-release/infra/.' "$fake_root/docker.log"
  health_line="$(grep -n 'compose .*exec -T reven python' "$fake_root/docker.log" | cut -d: -f1)"
  reload_line="$(grep -n 'compose .*exec -T caddy caddy reload' "$fake_root/docker.log" | cut -d: -f1)"
  [ "$health_line" -lt "$reload_line" ] || fail 'Caddy reloaded before the Reven health check'
  assert_no_temporary_resources
}

test_unchanged_caddy_skips_reload() {
  setup_case unchanged-caddy "$image_b"

  run_deploy deploy "$image_c" 0 0

  diff -r "$fake_root/images/c/infra" "$host_root/infra" >/dev/null || fail 'same-Caddy target infra was not synchronized'
  [ ! -e "$fake_root/reload-count" ] || fail 'unchanged Caddyfile triggered a reload'
  assert_not_contains 'exec -T caddy caddy reload' "$fake_root/docker.log"
  assert_no_temporary_resources
}

test_rollback_exports_recorded_image() {
  setup_case rollback "$image_a"
  printf '%s\n' "$image_b" >"$host_root/.previous-healthy-image"

  run_deploy rollback '' 0 0

  assert_equal "$image_b" "$(awk -F= '$1 == "REVEN_IMAGE" { print substr($0, length($1) + 2) }' "$host_root/.env")" \
    'rollback did not configure the recorded image'
  diff -r "$fake_root/images/b/infra" "$host_root/infra" >/dev/null || fail 'rollback image infra was not synchronized'
  assert_contains "create $image_b" "$fake_root/docker.log"
  assert_equal "$image_a" "$(cat "$host_root/.previous-healthy-image")" 'rollback did not retain the displaced image'
  assert_equal "$image_b" "$(cat "$host_root/.last-healthy-image")" 'rollback image was not recorded healthy'
  assert_no_temporary_resources
}

test_health_failure_restores_without_old_start() {
  setup_case health-failure "$image_b"
  printf '%s\n' "$image_c" >"$host_root/.previous-healthy-image"
  printf '%s\n' 'pre-existing stale content' >"$host_root/infra/pre-existing-file"
  chmod 755 "$host_root/infra/caddy/Caddyfile"
  chmod 600 "$fake_root/images/a/infra/caddy/Caddyfile"
  mkdir -p "$case_root/expected-infra"
  cp -R "$host_root/infra/." "$case_root/expected-infra/"

  if run_deploy deploy "$image_a" 1 0 >/dev/null 2>&1; then
    fail 'health failure unexpectedly succeeded'
  fi

  assert_equal "$image_b" "$(awk -F= '$1 == "REVEN_IMAGE" { print substr($0, length($1) + 2) }' "$host_root/.env")" \
    'health failure did not restore the prior image config'
  diff -r "$case_root/expected-infra" "$host_root/infra" >/dev/null || fail 'health failure did not restore prior infra'
  [ -x "$host_root/infra/caddy/Caddyfile" ] || fail 'health failure did not restore the prior Caddyfile mode'
  assert_equal "$image_b" "$(cat "$host_root/.last-healthy-image")" 'health failure changed last healthy history'
  assert_equal "$image_c" "$(cat "$host_root/.previous-healthy-image")" 'health failure changed previous healthy history'
  assert_contains "up-image=$image_a" "$fake_root/docker.log"
  assert_not_contains "up-image=$image_b" "$fake_root/docker.log"
  assert_equal '1' "$(cat "$fake_root/reload-count")" 'restored Caddy config should reload once after health failure'
  assert_equal 'caddy-b' "$(cat "$fake_root/loaded-caddy")" 'health failure did not restore loaded Caddy config'
  assert_no_temporary_resources
}

test_reload_failure_restores_config_and_infra() {
  setup_case reload-failure "$image_b"
  mkdir -p "$case_root/expected-infra"
  cp -R "$host_root/infra/." "$case_root/expected-infra/"

  if run_deploy deploy "$image_a" 0 1 >/dev/null 2>&1; then
    fail 'Caddy reload failure unexpectedly succeeded'
  fi

  assert_equal "$image_b" "$(awk -F= '$1 == "REVEN_IMAGE" { print substr($0, length($1) + 2) }' "$host_root/.env")" \
    'reload failure did not restore the prior image config'
  diff -r "$case_root/expected-infra" "$host_root/infra" >/dev/null || fail 'reload failure did not restore prior infra'
  assert_equal '2' "$(cat "$fake_root/reload-count")" 'reload failure should retry with the restored Caddy config'
  assert_equal 'caddy-b' "$(cat "$fake_root/loaded-caddy")" 'reload failure did not restore loaded Caddy config'
  assert_not_contains "up-image=$image_b" "$fake_root/docker.log"
  assert_no_temporary_resources
}

test_changed_caddy_success
test_unchanged_caddy_skips_reload
test_rollback_exports_recorded_image
test_health_failure_restores_without_old_start
test_reload_failure_restores_config_and_infra
printf '%s\n' 'deploy_reven integration tests passed'
