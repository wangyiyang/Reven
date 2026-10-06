#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

static_root=/srv/reven
release_id=$(cat /app/web-dist/.release)
release_dir="${static_root}/releases/${release_id}"
mkdir -p "${static_root}/releases"
exec 9>"${static_root}/.startup.lock"
flock -x 9

/app/.venv/bin/alembic -c /app/server/migrations/alembic.ini upgrade head
/app/.venv/bin/python -m reven.agent.checkpoint

staging_dir=$(mktemp -d "${static_root}/.release.XXXXXX")
trap 'rm -rf "${staging_dir}"' EXIT HUP INT TERM
cp -a /app/web-dist/. "${staging_dir}/"
if [ ! -d "${release_dir}" ]; then
    mv "${staging_dir}" "${release_dir}"
    staging_dir=$(mktemp -d "${static_root}/.release.XXXXXX")
fi
ln -s "releases/${release_id}" "${staging_dir}/current"
mv -Tf "${staging_dir}/current" "${static_root}/current"
rm -rf "${staging_dir}"
trap - EXIT HUP INT TERM
flock -u 9
exec 9>&-

exec /app/.venv/bin/uvicorn reven.app:app --host 0.0.0.0 --port 8000 --workers 1
