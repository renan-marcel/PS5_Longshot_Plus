#!/usr/bin/env bash
# tests/run_all.py in the longshot-tests image (scripts/docker/tests.Dockerfile) on this checkout as it is now, uncommitted
# changes included. The checkout is copied in (docker cp), not shared: Docker Desktop shares only the folders set in its
# settings, and the checks then run on Linux's own file system. Arguments go to run_all.py.
#
#   bash scripts/docker/run_all.sh                       every check
#   bash scripts/docker/run_all.sh tests/test_x.py       some
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
image=${LONGSHOT_TEST_IMAGE:-longshot-tests}
docker image inspect "$image" > /dev/null 2>&1 ||
    docker build -t "$image" -f "$root/scripts/docker/tests.Dockerfile" "$root"
name=longshot-tests-$$
trap 'docker rm -f "$name" > /dev/null 2>&1 || true' EXIT
# (Git Bash would turn /src into a Windows path)
export MSYS_NO_PATHCONV=1
docker create --name "$name" "$image" sleep infinity > /dev/null
docker start "$name" > /dev/null
src=$root
command -v cygpath > /dev/null && src=$(cygpath -m "$root")   # (Git Bash: docker wants C:/..., not /c/...)
docker cp "$src/." "$name:/src"
docker exec "$name" python3 -I -B tests/run_all.py "$@"
