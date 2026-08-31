#!/bin/sh
set -eu

: "${FAKE_DOCKER_ROOT:?}"
: "${FAKE_DEPLOY_DIR:?}"
health_failure="${FAKE_HEALTH_FAIL:-0}"
reload_failure_once="${FAKE_RELOAD_FAIL_ONCE:-0}"
log_file="$FAKE_DOCKER_ROOT/docker.log"

printf '%s\n' "$*" >>"$log_file"

case "$1" in
  pull)
    exit 0
    ;;
  image)
    [ "$2" = inspect ] || exit 1
    printf '%s\n' "$3"
    ;;
  create)
    printf '%s\n' "$2" >"$FAKE_DOCKER_ROOT/containers/fake-container"
    printf '%s\n' 'fake-container'
    ;;
  cp)
    export_source="$2"
    export_destination="$3"
    container_name=${export_source%%:*}
    export_image="$(cat "$FAKE_DOCKER_ROOT/containers/$container_name")"
    digest=${export_image##*sha256:}
    case "$digest" in
      a*) fixture_name=a ;;
      b*) fixture_name=b ;;
      c*) fixture_name=c ;;
      *) exit 1 ;;
    esac
    cp -R "$FAKE_DOCKER_ROOT/images/$fixture_name/infra/." "$export_destination/"
    ;;
  rm)
    rm -f "$FAKE_DOCKER_ROOT/containers/$2"
    ;;
  compose)
    shift
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --env-file|-f)
          shift 2
          ;;
        *)
          break
          ;;
      esac
    done
    compose_command="$1"
    shift
    case "$compose_command" in
      pull)
        exit 0
        ;;
      ps)
        if [ -f "$FAKE_DOCKER_ROOT/caddy-running" ]; then
          printf '%s\n' 'fake-caddy-container'
        fi
        ;;
      up)
        starts_caddy=0
        for up_arg in "$@"; do
          [ "$up_arg" = caddy ] && starts_caddy=1
        done
        if [ "$starts_caddy" -eq 1 ]; then
          : >"$FAKE_DOCKER_ROOT/caddy-running"
          cp "$FAKE_DEPLOY_DIR/infra/caddy/Caddyfile" "$FAKE_DOCKER_ROOT/loaded-caddy"
        else
          configured_image="$(awk -F= '$1 == "REVEN_IMAGE" { print substr($0, length($1) + 2) }' "$FAKE_DEPLOY_DIR/.env")"
          printf 'up-image=%s\n' "$configured_image" >>"$log_file"
          # Reven 不健康时 depends_on(service_healthy) 阻止 Caddy 启动
          if [ "$health_failure" -eq 0 ]; then
            : >"$FAKE_DOCKER_ROOT/caddy-running"
          else
            rm -f "$FAKE_DOCKER_ROOT/caddy-running"
          fi
        fi
        ;;
      exec)
        [ "$1" = -T ] || exit 1
        service="$2"
        case "$service" in
          reven)
            [ "$health_failure" -eq 0 ] || exit 1
            ;;
          caddy)
            # 对已停止的容器执行 exec 必然失败（真实 docker 行为）
            [ -f "$FAKE_DOCKER_ROOT/caddy-running" ] || exit 1
            reload_count=0
            if [ -f "$FAKE_DOCKER_ROOT/reload-count" ]; then
              reload_count="$(cat "$FAKE_DOCKER_ROOT/reload-count")"
            fi
            reload_count=$((reload_count + 1))
            printf '%s\n' "$reload_count" >"$FAKE_DOCKER_ROOT/reload-count"
            if [ "$reload_failure_once" -eq 1 ] && [ "$reload_count" -eq 1 ]; then
              exit 1
            fi
            cp "$FAKE_DEPLOY_DIR/infra/caddy/Caddyfile" "$FAKE_DOCKER_ROOT/loaded-caddy"
            ;;
          *) exit 1 ;;
        esac
        ;;
      *) exit 1 ;;
    esac
    ;;
  *) exit 1 ;;
esac
