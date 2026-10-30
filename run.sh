#!/usr/bin/env bash
# Brings up the whole platform: core infra -> service images -> frontend ->
# agents -> gateway -> health checks. Shows one line per step; the full
# output of every command goes to .run/run.log (shown on failure).
#
#   ./run.sh              reuse existing images; rebuild only the ones whose
#                         source changed since their last build
#   ./run.sh --build      rebuild every image and the frontend
#   ./run.sh --no-build   never build; just start the existing images
#   ./run.sh --verbose    stream all command output to the terminal too
#
# Individual pieces: scripts/test-service.sh (per-service pytest),
# scripts/seed-demo-data.sh (demo vendor + approved purchase request).
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")" && pwd)
cd "$ROOT_DIR"

BUILD_MODE=changed
VERBOSE=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD_MODE=all ;;
    --no-build) BUILD_MODE=none ;;
    -v|--verbose) VERBOSE=1 ;;
    -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see ./run.sh --help)" >&2; exit 2 ;;
  esac
done

# Same project name Compose derives from the folder (scripts/test-service.sh
# uses it too), so image names are "<project>-<service>".
PROJECT_NAME=$(basename "$ROOT_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9')
STATE_DIR="$ROOT_DIR/.run"
STAMPS="$STATE_DIR/stamps"
LOG="$STATE_DIR/run.log"
mkdir -p "$STAMPS"
: > "$LOG"

# Services built from a Dockerfile (workers reuse their service's image).
IMAGE_SERVICES="auth-service document-vendor-agent approval-inventory-agent contract-risk-agent notification-agent chatbot-agent"
# Started by step 4, and checked by step 6 together with CORE_CHECK.
APP_SERVICES="auth-service document-vendor-agent document-vendor-agent-worker approval-inventory-agent approval-inventory-agent-worker contract-risk-agent contract-risk-agent-worker notification-agent chatbot-agent mlflow kafka-exporter documenso"
CORE_CHECK="postgres redis redpanda minio temporal clamav"
TOTAL_STEPS=6

if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'; TTY=1
else
  BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; RESET=""; TTY=0
fi

fmt_time() { local s=$1; if [ "$s" -ge 60 ]; then echo "$((s / 60))m$((s % 60))s"; else echo "${s}s"; fi; }

STEP=0
STEP_LABEL=""
step() {
  STEP=$((STEP + 1))
  STEP_LABEL="$1"
  STEP_START=$SECONDS
  printf '%s[%3d%%]%s %s\n' "$BOLD" $((STEP * 100 / TOTAL_STEPS)) "$RESET" "$STEP_LABEL"
  echo "===== [$STEP/$TOTAL_STEPS] $STEP_LABEL =====" >> "$LOG"
}
# One indented result line under the current step.
note() { printf '       %s\n' "$*"; }

fail() {
  [ "$TTY" = 1 ] && printf '\r\033[K'
  printf '\n%sERROR:%s %s\n' "$RED$BOLD" "$RESET" "$1" >&2
  if [ "${2:-}" != "nolog" ]; then
    printf '%sLast lines of %s:%s\n' "$DIM" "${LOG#"$ROOT_DIR"/}" "$RESET" >&2
    grep -v '^[[:space:]]*$' "$LOG" | tail -n 25 | sed 's/^/  /' >&2
  fi
  exit 1
}

# run "<what is happening>" cmd... — runs cmd with its output in the log,
# showing a one-line timer while it runs; on failure prints the log tail.
run() {
  local what="$1"; shift
  echo "\$ $*" >> "$LOG"
  if [ "$VERBOSE" = 1 ]; then
    "$@" 2>&1 | tee -a "$LOG" || fail "$what failed"
    return 0
  fi
  "$@" >> "$LOG" 2>&1 &
  local pid=$! start=$SECONDS
  if [ "$TTY" = 1 ]; then
    while kill -0 "$pid" 2>/dev/null; do
      printf '\r\033[K       %s%s… %s%s' "$DIM" "$what" "$(fmt_time $((SECONDS - start)))" "$RESET"
      sleep 1
    done
    printf '\r\033[K'
  fi
  wait "$pid" || fail "$what failed"
}

# --- change detection --------------------------------------------------------
# A service/frontend is "changed" when a source file is newer than the stamp
# written after its last successful build by this script.
source_dirs() {
  case "$1" in
    frontend) echo "frontend" ;;
    approval-inventory-agent) echo "services/$1 shared data/synthetic-sso-logs" ;;
    *) echo "services/$1 shared" ;;
  esac
}
has_changes() {
  local stamp="$STAMPS/$1"
  [ -f "$stamp" ] || return 0
  # shellcheck disable=SC2046
  [ -n "$(find $(source_dirs "$1") -path '*/node_modules' -prune -o -path 'frontend/dist' -prune -o -type f -newer "$stamp" \
      -not -path '*/tests/*' -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' \
      -not -name '*.pyc' -not -name '.DS_Store' -print 2>/dev/null | head -n 1)" ]
}
image_exists() { docker image inspect "$PROJECT_NAME-$1" >/dev/null 2>&1; }

STARTED=$SECONDS
printf '\n%sIT Procurement Platform%s  %s(log: .run/run.log)%s\n\n' "$BOLD" "$RESET" "$DIM" "$RESET"

# --- 1. core infra -------------------------------------------------------------
step "Core infrastructure (Postgres, Kafka, MinIO, Temporal, ClamAV…)"
run "Starting Docker and core services" ./install.sh
note "${GREEN}✓${RESET} ready ($(fmt_time $((SECONDS - STEP_START))))"

# --- 2. images -----------------------------------------------------------------
step "Service images"
TO_BUILD=""
for svc in $IMAGE_SERVICES; do
  if ! image_exists "$svc"; then
    [ "$BUILD_MODE" = none ] && fail "No image for $svc yet — run ./run.sh without --no-build first." nolog
    TO_BUILD="$TO_BUILD $svc"
  elif [ "$BUILD_MODE" = all ]; then
    TO_BUILD="$TO_BUILD $svc"
  elif [ "$BUILD_MODE" = changed ]; then
    if [ ! -f "$STAMPS/$svc" ]; then
      # Image built before this script tracked builds: trust it.
      touch "$STAMPS/$svc"
    elif has_changes "$svc"; then
      TO_BUILD="$TO_BUILD $svc"
    fi
  fi
done
if [ -n "$TO_BUILD" ]; then
  # shellcheck disable=SC2086
  run "Building$TO_BUILD" docker compose build $TO_BUILD
  for svc in $TO_BUILD; do touch "$STAMPS/$svc"; done
  note "${GREEN}✓${RESET} built:$TO_BUILD ($(fmt_time $((SECONDS - STEP_START))))"
else
  note "${GREEN}✓${RESET} reusing existing images ${DIM}(./run.sh --build to force a rebuild)${RESET}"
fi

# --- 3. frontend -------------------------------------------------------------
step "Frontend (React/Vite → frontend/dist)"
need_frontend=0
if [ ! -f frontend/dist/index.html ]; then
  [ "$BUILD_MODE" = none ] && fail "frontend/dist is missing — run ./run.sh without --no-build first." nolog
  need_frontend=1
elif [ "$BUILD_MODE" = all ] || { [ "$BUILD_MODE" = changed ] && has_changes frontend; }; then
  need_frontend=1
fi
if [ "$need_frontend" = 1 ]; then
  # Built in a node container so the host needs no Node. node_modules lives
  # in a named volume (kept out of the host checkout, where Linux binaries
  # would break a host build) and is reinstalled only when the lockfile changes.
  run "Building frontend" docker run --rm \
    -v "$ROOT_DIR/frontend:/app" \
    -v "${PROJECT_NAME}_frontend-node-modules:/app/node_modules" \
    -w /app node:20-alpine \
    sh -c 'if ! cmp -s package-lock.json node_modules/.installed-lock; then npm ci --no-audit --no-fund && cp package-lock.json node_modules/.installed-lock; fi && npm run build'
  touch "$STAMPS/frontend"
  note "${GREEN}✓${RESET} built ($(fmt_time $((SECONDS - STEP_START))))"
else
  [ -f "$STAMPS/frontend" ] || touch "$STAMPS/frontend"
  note "${GREEN}✓${RESET} up to date"
fi

# --- 4. agents -----------------------------------------------------------------
step "Starting agents and workers"
# Documenso seals signed contracts with this certificate; make a
# development one the first time (scripts/documenso_setup.py does the rest).
if [ ! -f secrets/documenso/cert.p12 ]; then
  run "Making Documenso's signing certificate" sh -c '
    mkdir -p secrets/documenso && cd secrets/documenso &&
    openssl req -x509 -newkey rsa:2048 -sha256 -days 1095 -nodes -keyout key.pem -out cert.pem \
      -subj "/CN=Procurement Platform e-signature (development)" &&
    pass="pass:${DOCUMENSO_SIGNING_PASSPHRASE:-dev-documenso-signing}" &&
    { openssl pkcs12 -export -legacy -out cert.p12 -inkey key.pem -in cert.pem -passout "$pass" ||
      openssl pkcs12 -export -out cert.p12 -inkey key.pem -in cert.pem -passout "$pass"; } &&
    chmod 644 cert.p12'
fi
# shellcheck disable=SC2086
run "Starting containers" docker compose up -d --remove-orphans $APP_SERVICES
note "${GREEN}✓${RESET} started ($(fmt_time $((SECONDS - STEP_START))))"

# --- 5. gateway --------------------------------------------------------------
step "Gateway (nginx on :8080)"
# nginx resolves every upstream hostname at boot, so it is recreated after
# the services above exist.
run "Recreating nginx" docker compose up -d --force-recreate nginx
note "${GREEN}✓${RESET} started"

# --- 6. health -----------------------------------------------------------------
step "Health checks"
CHECK="$CORE_CHECK $APP_SERVICES nginx"
svc_status() {
  local cid
  cid=$(docker compose ps -a -q "$1" 2>/dev/null || true)
  [ -z "$cid" ] && { echo "missing"; return; }
  docker inspect --format '{{if eq .State.Status "running"}}{{if .State.Health}}{{.State.Health.Status}}{{else}}running{{end}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo "unknown"
}
MAX_WAIT=450
waiting=""
while :; do
  waiting=""
  for svc in $CHECK; do
    st=$(svc_status "$svc")
    case "$st" in healthy|running) ;; *) waiting="$waiting $svc($st)" ;; esac
  done
  [ -z "$waiting" ] && break
  elapsed=$((SECONDS - STEP_START))
  [ "$elapsed" -ge "$MAX_WAIT" ] && break
  if [ "$TTY" = 1 ]; then
    printf '\r\033[K       %swaiting on:%s %s' "$DIM" "$waiting" "$(fmt_time "$elapsed")$RESET"
  fi
  sleep 3
done
[ "$TTY" = 1 ] && printf '\r\033[K'

# Agent table: name, port, status.
print_row() {
  local name=$1 port=$2 st mark
  st=$(svc_status "$name")
  case "$st" in
    healthy|running) mark="${GREEN}✓${RESET}" ;;
    starting) mark="${YELLOW}…${RESET}" ;;
    *) mark="${RED}✗${RESET}" ;;
  esac
  printf '       %s %-32s %-6s %s%s%s\n' "$mark" "$name" "$port" "$DIM" "$st" "$RESET"
}
print_row auth-service                    :8005
print_row document-vendor-agent           :8001
print_row document-vendor-agent-worker    ""
print_row approval-inventory-agent        :8002
print_row approval-inventory-agent-worker ""
print_row contract-risk-agent             :8003
print_row contract-risk-agent-worker      ""
print_row notification-agent              :8004
print_row chatbot-agent                   :8006
print_row documenso                       :3010
print_row nginx                           :8080

if [ -n "$waiting" ]; then
  printf '\n%sERROR:%s not healthy after %s:%s\n' "$RED$BOLD" "$RESET" "$(fmt_time $MAX_WAIT)" "$waiting" >&2
  for entry in $waiting; do
    svc=${entry%%(*}
    printf '\n%s--- %s ---%s\n' "$BOLD" "$svc" "$RESET" >&2
    cid=$(docker compose ps -a -q "$svc" 2>/dev/null || true)
    if [ -n "$cid" ]; then
      docker inspect --format='{{if .State.Health}}{{range .State.Health.Log}}{{.Output}}{{end}}{{end}}' "$cid" 2>/dev/null | tail -n 3 >&2 || true
    fi
    docker compose logs --no-log-prefix --tail 15 "$svc" 2>&1 | sed 's/^/  /' >&2 || true
  done
  exit 1
fi

printf '\n%s✓ Stack is up%s in %s\n\n' "$GREEN$BOLD" "$RESET" "$(fmt_time $((SECONDS - STARTED)))"
cat <<EOF
  App          http://localhost:8080   (requester|approver|finance|admin@demo.example.com / DemoPass123!)
  Mailpit      http://localhost:8025   Temporal UI  http://localhost:8088
  Grafana      http://localhost:3000   MinIO        http://localhost:9001
  Prometheus   http://localhost:9090   MLflow       http://localhost:5050

  Demo data: ./scripts/seed-demo-data.sh    Tests: ./scripts/test-service.sh all | make e2e
EOF
if ! grep -q '^APP_DOCUMENSO_API_TOKEN=.' .env 2>/dev/null; then
  printf '\n  %sE-signature:%s contracts use the built-in e-sign until Documenso is set up, once:\n' "$YELLOW" "$RESET"
  printf '    python3 scripts/documenso_setup.py && docker compose up -d contract-risk-agent contract-risk-agent-worker && docker compose restart nginx\n'
fi
