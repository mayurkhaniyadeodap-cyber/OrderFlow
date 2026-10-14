#!/usr/bin/env bash
# OrderFlow deploy script for the live server (care.deodap.info/orderflow).
#
# Installed by hand as /home/ubuntu/orderflow-deploy/deploy.sh. It is the ONLY command the GitHub Actions SSH key
# may run (forced command in ~/.ssh/authorized_keys), so a push to GitHub can never change what that key can do.
#
#   deploy <commit>   deploy a commit of GitHub main: backup, copy code, restart OrderFlow, health check,
#                     automatic rollback of the code if the check fails
#   check <commit>    dry run: download + build + verify only (no backup, no copy, no restart)
#   rollback          restore the code snapshot taken before the last deploy and restart OrderFlow
#   status            show the deployed commit and the health check
#
# Never touched: backend/.env, the database, uploads, backups, the Python virtual environment, other projects,
# nginx or systemd configuration. Nothing in the app folder is ever deleted (copy without --delete).
set -euo pipefail
umask 022

APP=/var/www/orderflow
BASE=/home/ubuntu/orderflow-deploy
REPO_URL=https://github.com/mayurkhaniyadeodap-cyber/OrderFlow.git
BRANCH=main
SERVICE=orderflow                      # the only service this script ever restarts
APP_URL=http://127.0.0.1:8040          # uvicorn behind nginx /orderflow/
WEB_BASE=/orderflow/                   # sub-path the web app is built for

MIRROR=$BASE/repo.git
STAGE=$BASE/stage
SNAPSHOTS=$BASE/code-backups
LOG=$BASE/deploy.log
STATE=$BASE/deployed-commit

# Paths (relative to the app folder) that are never copied over, overwritten or put in a code snapshot.
PROTECT=(
  --exclude=/backend/.env --exclude='/backend/*.db' --exclude='/backend/*.db-*'
  --exclude=/backend/uploads/ --exclude=/backend/backups/ --exclude=/backend/backup.log
  --exclude=/backend/.venv/ --exclude=/frontend/node_modules/
  --exclude=__pycache__/ --exclude=.pytest_cache/
)

mkdir -p "$BASE" "$SNAPSHOTS"
exec > >(tee -a "$LOG") 2>&1
log() { echo "[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"; }
fail() { log "FAILED: $*"; exit 1; }

# One deploy at a time.
exec 9>"$BASE/.lock"
flock -n 9 || fail "another deploy is already running"

read -r ACTION ARG EXTRA <<<"${SSH_ORIGINAL_COMMAND:-${*:-}}" || true
[[ -z "${EXTRA:-}" ]] || fail "unexpected arguments"

fetch_commit() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]] || fail "a full 40-character commit id is required"
  [[ -d "$MIRROR" ]] || git clone --quiet --bare "$REPO_URL" "$MIRROR"
  git -C "$MIRROR" fetch --quiet --prune origin "+refs/heads/$BRANCH:refs/heads/$BRANCH"
  git -C "$MIRROR" cat-file -e "$1^{commit}" 2>/dev/null || fail "commit $1 not found on GitHub"
  git -C "$MIRROR" merge-base --is-ancestor "$1" "$BRANCH" || fail "commit $1 is not on GitHub $BRANCH"
}

build_stage() {
  local commit=$1
  [[ "$STAGE" == "$BASE/stage" ]] && rm -rf "$STAGE"    # our own build area only
  mkdir -p "$STAGE"
  git -C "$MIRROR" archive "$commit" | tar -x -C "$STAGE"
  log "building the web app for $WEB_BASE"
  (cd "$STAGE/frontend" && npm ci --no-audit --no-fund --loglevel=error && ORDERFLOW_BASE="$WEB_BASE" npm run build --silent)
  grep -q "${WEB_BASE}assets/" "$STAGE/frontend/dist/index.html" || fail "web app was not built for $WEB_BASE"
  "$APP/backend/.venv/bin/python" -m compileall -q "$STAGE/backend/app" >/dev/null || fail "Python syntax check failed"
  echo "$commit" > "$STAGE/.commit"
}

healthy() {
  local health="" page asset
  for _ in $(seq 1 30); do
    health=$(curl -fsS -m 5 "$APP_URL/api/health" 2>/dev/null) && [[ $health == *'"status":"ok"'* ]] && break
    health=""
    sleep 1
  done
  [[ -n $health ]] || { log "health check: API not answering"; return 1; }
  [[ $health == *'"database":"ok"'* ]] || { log "health check: database not ok"; return 1; }
  page=$(curl -fsS -m 5 "$APP_URL/") || { log "health check: web page not served"; return 1; }
  asset=$(grep -o "${WEB_BASE}assets/[^\"]*\.js" <<<"$page" | head -1)
  [[ -n "$asset" ]] || { log "health check: page has no script"; return 1; }
  curl -fsS -m 5 -o /dev/null "$APP_URL/${asset#"$WEB_BASE"}" || { log "health check: $asset not served"; return 1; }
  log "health check passed (API, database, web page, $asset)"
}

restart_app() {
  log "restarting $SERVICE.service (no other service is touched)"
  sudo -n systemctl restart "$SERVICE"
}

snapshot_code() {
  local name="$SNAPSHOTS/$(date -u +%Y%m%d_%H%M%S)-$(cat "$STATE" 2>/dev/null | cut -c1-7 || echo unknown).tgz"
  tar -cz -C "$APP" \
    --exclude=./backend/.env --exclude='./backend/*.db' --exclude='./backend/*.db-*' \
    --exclude=./backend/uploads --exclude=./backend/backups --exclude=./backend/backup.log \
    --exclude=./backend/.venv --exclude=./frontend/node_modules --exclude=__pycache__ --exclude=.pytest_cache \
    -f "$name" .
  echo "$name"
}

restore_snapshot() {
  local snap=$1 tmp
  tmp=$(mktemp -d "$BASE/restore.XXXXXX")
  tar -xz -C "$tmp" -f "$snap"
  rsync -a "${PROTECT[@]}" "$tmp/" "$APP/"
  rm -rf "$tmp"                                           # temporary extraction folder only
}

case "${ACTION:-}" in
  check)
    log "CHECK ${ARG:-?} (dry run: nothing is installed or restarted)"
    fetch_commit "${ARG:-}"
    build_stage "$ARG"
    log "check passed for $ARG"
    ;;

  deploy)
    log "DEPLOY ${ARG:-?}"
    fetch_commit "${ARG:-}"
    build_stage "$ARG"

    log "backing up data (database + uploads) before the update"
    (cd "$APP/backend" && .venv/bin/python -m app.manage backup) || fail "data backup failed; nothing was changed"
    SNAP=$(snapshot_code) || fail "code snapshot failed; nothing was changed"
    echo "$SNAP" > "$BASE/last-snapshot"
    log "code snapshot: $SNAP"

    if ! cmp -s "$STAGE/backend/requirements.txt" "$APP/backend/requirements.txt"; then
      log "requirements.txt changed: installing Python packages"
      "$APP/backend/.venv/bin/pip" install --quiet -r "$STAGE/backend/requirements.txt" || fail "pip install failed; code not changed"
    fi

    log "copying new code (protected: .env, database, uploads, backups, .venv)"
    rsync -a "${PROTECT[@]}" --exclude=/.commit "$STAGE/" "$APP/"
    restart_app
    if healthy; then
      echo "$ARG" > "$STATE"
      log "DEPLOYED $ARG"
    else
      log "health check failed: rolling back to $SNAP"
      restore_snapshot "$SNAP"
      restart_app
      healthy && log "rolled back; OrderFlow is running the previous code" || log "ROLLBACK HEALTH CHECK FAILED - check the server"
      exit 1
    fi
    ;;

  rollback)
    SNAP=$(cat "$BASE/last-snapshot" 2>/dev/null) || fail "no snapshot recorded"
    [[ -f "$SNAP" ]] || fail "snapshot $SNAP not found"
    log "ROLLBACK to $SNAP"
    restore_snapshot "$SNAP"
    restart_app
    healthy || fail "health check failed after rollback"
    log "rollback done"
    ;;

  status)
    echo "deployed commit: $(cat "$STATE" 2>/dev/null || echo unknown)"
    systemctl is-active "$SERVICE"
    healthy
    ;;

  *)
    fail "usage: deploy <commit> | check <commit> | rollback | status"
    ;;
esac
