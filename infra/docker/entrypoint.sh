#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

static_root=/srv/reven
release_id=$(cat /app/web-dist/.release)
release_dir="${static_root}/releases/${release_id}"
staging_dir="${release_dir}.tmp.$$"
link_tmp="${static_root}/.current.$$"

mkdir -p "${static_root}/releases"
rm -rf "${staging_dir}"
mkdir -p "${staging_dir}"
cp -a /app/web-dist/. "${staging_dir}/"
if [ ! -d "${release_dir}" ]; then
    mv "${staging_dir}" "${release_dir}"
else
    rm -rf "${staging_dir}"
fi
ln -s "releases/${release_id}" "${link_tmp}"
mv -Tf "${link_tmp}" "${static_root}/current"

/app/.venv/bin/alembic -c /app/server/migrations/alembic.ini upgrade head
exec /app/.venv/bin/uvicorn reven.app:app --host 0.0.0.0 --port 8000 --workers 1
