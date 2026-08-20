#!/bin/bash
set -eu

target="tests/specification_tests/client-specification"
stamp="${target}/.spec-version"
lock="${target}.lock"
tmp="${target}.tmp.$$"

specversion=$(python -c "from UnleashClient.constants import CLIENT_SPEC_VERSION; print(CLIENT_SPEC_VERSION)")

# Fast path. Several tox environments run this concurrently under
# `tox --parallel`, so all but the first must not touch the directory.
if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$specversion" ]; then
  echo "Client spec ${specversion} already present, skipping download."
  exit 0
fi

# `mkdir` is atomic on ext4, APFS and NTFS, so exactly one process wins the
# lock and downloads. flock is not used because this also runs under Git Bash
# on the Windows runner.
if mkdir "$lock" 2>/dev/null; then
  trap 'rm -rf "$lock" "$tmp"' EXIT INT TERM

  echo "Downloading client spec ${specversion}"
  rm -rf "$tmp" "$target"
  git -c advice.detachedHead=false clone --quiet --depth 1 --branch v"${specversion}" \
    https://github.com/Unleash/client-specification.git "$tmp"
  echo "$specversion" > "${tmp}/.spec-version"

  # Renaming a directory on the same filesystem is atomic, so a concurrent
  # reader never sees a partially populated specifications/ directory.
  mv "$tmp" "$target"
  exit 0
fi

echo "Another process is downloading client spec ${specversion}; waiting..."
waited=0
while [ "$waited" -lt 180 ]; do
  if [ -f "$stamp" ] && [ "$(cat "$stamp")" = "$specversion" ]; then
    exit 0
  fi
  sleep 1
  waited=$((waited + 1))
done

echo "Timed out waiting for client spec ${specversion}." >&2
echo "If a previous run was interrupted, remove the stale lock: rm -rf ${lock}" >&2
exit 1
