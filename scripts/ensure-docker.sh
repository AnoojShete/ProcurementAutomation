#!/usr/bin/env bash
# Makes sure the Docker daemon is actually running before install.sh/run.sh
# try to talk to it — starting it automatically where that's possible
# instead of just failing with "cannot connect to the Docker daemon".
#
# Covers three cases:
#   - macOS: launch Docker Desktop (open -a Docker) if it isn't running.
#   - WSL2 (Windows via Docker Desktop's WSL integration): Docker Desktop
#     itself runs on the Windows host, not inside WSL, so it's launched via
#     WSL's interop (powershell.exe/cmd.exe), not a Linux command.
#   - Native Linux: try the user-level `docker-desktop` service first
#     (Docker Desktop for Linux), then fall back to `systemctl start
#     docker` (traditional Docker Engine, e.g. on Ubuntu) — this needs
#     sudo, so it only runs if the daemon is confirmed *not running*
#     rather than just inaccessible to this user (a permission problem
#     doesn't get fixed by starting anything, see the group-membership
#     hint below).
#
# Safe to source or run standalone; always leaves docker info working or
# exits 1 with a clear next step.
set -e

_wait_for_docker() {
  local max="${1:-60}"
  echo -n "Waiting for Docker to become ready"
  for _ in $(seq 1 "$max"); do
    if docker info >/dev/null 2>&1; then
      echo " ready."
      return 0
    fi
    echo -n "."
    sleep 2
  done
  echo
  return 1
}

_is_wsl() {
  [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null
}

if docker info >/dev/null 2>&1; then
  : # already running — nothing to do
elif [[ "$OSTYPE" == "darwin"* ]]; then
  echo "Docker Desktop is not running. Starting it..."
  open -a Docker
  _wait_for_docker || {
    echo "Docker Desktop did not become ready in time. Start it manually from the menu bar and re-run this script." >&2
    exit 1
  }
elif _is_wsl; then
  echo "Docker Desktop is not running. Starting it on the Windows host from WSL..."
  # Docker Desktop's daemon runs on the Windows side even under WSL2's
  # integration, so it has to be launched via Windows, not a Linux
  # command — WSL can invoke Windows executables directly (interop).
  powershell.exe -NoProfile -Command "Start-Process 'Docker Desktop'" >/dev/null 2>&1 \
    || cmd.exe /c start "" "Docker Desktop" >/dev/null 2>&1 \
    || true
  _wait_for_docker || {
    echo "Docker Desktop did not become ready in time." >&2
    echo "Start it manually on Windows, and make sure Settings > Resources > WSL Integration has this distro enabled." >&2
    exit 1
  }
else
  # Native Linux. Distinguish "not running" (try to start it) from
  # "running but this user can't reach it" (starting won't help — the
  # usermod fix is the only fix).
  err=$(docker info 2>&1 >/dev/null || true)
  if echo "$err" | grep -qi "permission denied"; then
    echo "Docker daemon is not accessible by the current user." >&2
    echo "If you see permission denied, run:" >&2
    echo "  sudo usermod -aG docker $USER && newgrp docker" >&2
    exit 1
  fi

  echo "Docker daemon is not running. Attempting to start it..."
  if command -v systemctl >/dev/null 2>&1 && systemctl --user start docker-desktop >/dev/null 2>&1; then
    : # Docker Desktop for Linux, started as a user service
  elif command -v systemctl >/dev/null 2>&1; then
    echo "Starting the Docker Engine service (requires sudo)..."
    sudo systemctl start docker
  elif command -v service >/dev/null 2>&1; then
    sudo service docker start
  fi
  _wait_for_docker || {
    echo "Could not start the Docker daemon automatically. Start it manually, e.g.:" >&2
    echo "  sudo systemctl start docker" >&2
    exit 1
  }
fi
