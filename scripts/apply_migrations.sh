#!/usr/bin/env bash
# Apply pending Supabase SQL migrations to a Postgres database, idempotently and
# concurrency-safely, tracking applied versions + SHA-256 checksums in a private
# ledger (taxflow_internal.applied_migrations).
#
# WHERE THIS RUNS / WHICH DB URL:
#   Runs on the GitHub-hosted runner during `deploy-backend` (before the image
#   build/up), NOT on the droplet. It requires a dedicated MIGRATION_DATABASE_URL
#   pointing at the Supabase SESSION POOLER (port 5432) — IPv4-reachable from
#   GitHub runners and session-scoped (supports --single-transaction DDL +
#   advisory locks). The app's DATABASE_URL may be an IPv6-only direct endpoint,
#   so this script never falls back to it. The TRANSACTION pooler (port 6543) is
#   session-incompatible (no advisory locks / session state) and is HARD-REFUSED.
#     doppler run --project taxflow --config prd -- bash scripts/apply_migrations.sh
#
# EXPAND/CONTRACT POLICY:
#   Migrations auto-apply BEFORE the new image builds/deploys, and a migration
#   persists even if the build/smoke/rollback later fails. So only additive,
#   backward-compatible (EXPAND) migrations may auto-apply here — they must be
#   safe against the currently-running image. Destructive (CONTRACT) changes ship
#   in a LATER deploy, after the old code is gone. 038–041 are all additive.
#
# BOOTSTRAP:
#   Migrations 038–041 use bare CREATE TABLE / ADD COLUMN / CREATE INDEX (no
#   IF NOT EXISTS), so re-running them against an already-migrated DB errors. To
#   adopt this runner against a DB whose schema is already ahead of the (empty)
#   ledger, seed the ledger WITHOUT re-running SQL:
#     bash scripts/apply_migrations.sh --mark-applied-through 040
#   This runs a schema PREFLIGHT (verifies the ≤040 objects actually exist) and
#   then records 001..040 as applied with their real checksums. The next normal
#   run applies only 041+.
set -euo pipefail

# Advisory-lock key: an arbitrary but fixed constant so all runs contend on the
# same lock (serializes concurrent deploys / manual runs).
readonly LOCK_KEY=8274651

usage() {
  cat >&2 <<'USAGE'
Usage:
  apply_migrations.sh                          Apply all pending migrations.
  apply_migrations.sh --mark-applied-through NNN
                                               Record 001..NNN as applied WITHOUT
                                               running SQL (bootstrap; runs a
                                               schema preflight first).
USAGE
}

MARK_THROUGH=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mark-applied-through)
      MARK_THROUGH="${2:-}"
      if [ -z "$MARK_THROUGH" ]; then
        echo "ERROR: --mark-applied-through requires a version argument (e.g. 040)." >&2
        exit 1
      fi
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

# --- resolve + validate the migration DB URL --------------------------------
if [ -z "${MIGRATION_DATABASE_URL:-}" ]; then
  echo "ERROR: MIGRATION_DATABASE_URL is not set." >&2
  echo "       Set it to the Supabase SESSION POOLER URL (port 5432) and run via:" >&2
  echo "       doppler run --project taxflow --config prd -- bash scripts/apply_migrations.sh" >&2
  echo "       (DATABASE_URL is NOT used as a fallback — it may be an IPv6-only direct endpoint.)" >&2
  exit 1
fi
DB_URL="$MIGRATION_DATABASE_URL"

# Hard-refuse the transaction pooler (port 6543): it does not support session
# state / advisory locks / --single-transaction DDL the way this runner needs.
case "$DB_URL" in
  *:6543*)
    echo "ERROR: MIGRATION_DATABASE_URL points at the transaction pooler (:6543)." >&2
    echo "       Use the SESSION pooler (port 5432) instead — the transaction pooler" >&2
    echo "       cannot hold session advisory locks or run --single-transaction DDL." >&2
    exit 1
    ;;
esac

MIGRATIONS_DIR="$(cd "$(dirname "$0")/.." && pwd)/apps/backend/supabase/migrations"
if [ ! -d "$MIGRATIONS_DIR" ]; then
  echo "ERROR: migrations directory not found: $MIGRATIONS_DIR" >&2
  exit 1
fi

# --- enumerate + validate migration files -----------------------------------
# Sort by numeric prefix (files are NNN_*.sql). Populate parallel arrays of
# version / filename / path / checksum, rejecting bad names + duplicate versions.
declare -a VERSIONS=() FILES=() PATHS=() SUMS=()
declare -A SEEN_VERSION=()

# Sorted lexically — the zero-padded 3-digit prefix makes lexical == numeric.
while IFS= read -r path; do
  [ -z "$path" ] && continue
  fname="$(basename "$path")"
  if ! [[ "$fname" =~ ^[0-9]{3}_[a-z0-9_]+\.sql$ ]]; then
    echo "ERROR: migration filename does not match ^[0-9]{3}_[a-z0-9_]+\\.sql\$: $fname" >&2
    exit 1
  fi
  version="${fname:0:3}"
  if [ -n "${SEEN_VERSION[$version]:-}" ]; then
    echo "ERROR: duplicate migration version '$version': $fname and ${SEEN_VERSION[$version]}" >&2
    exit 1
  fi
  SEEN_VERSION[$version]="$fname"
  sum="$(sha256sum "$path" | awk '{print $1}')"
  VERSIONS+=("$version")
  FILES+=("$fname")
  PATHS+=("$path")
  SUMS+=("$sum")
done < <(find "$MIGRATIONS_DIR" -maxdepth 1 -name '*.sql' | sort)

if [ "${#VERSIONS[@]}" -eq 0 ]; then
  echo "ERROR: no migration files found in $MIGRATIONS_DIR" >&2
  exit 1
fi

# --- psql helpers ------------------------------------------------------------
# One-shot query returning a single scalar (tuples-only, unaligned).
psql_scalar() {
  psql "$DB_URL" -v ON_ERROR_STOP=1 -qtA -c "$1"
}

# --- concurrency: hold a session advisory lock for the whole run -------------
# Advisory locks are session-scoped, so we keep ONE persistent psql session open
# for the duration of the run (fed SQL via a coprocess fd) and take the lock in
# it first. Holding that session open serializes the pending-check + applies
# against any overlapping deploy/manual run; explicitly unlocking + quitting and
# closing the fd (EOF) at the end lets the session release the lock and exit.
LOCK_SESSION_PID=""

acquire_lock() {
  # Start a persistent psql reading SQL from fd LOCK_FD; keep it open for the run.
  coproc LOCK_PROC { psql "$DB_URL" -v ON_ERROR_STOP=1 -qtA 2>&1; }
  LOCK_SESSION_PID=$LOCK_PROC_PID
  exec {LOCK_FD}>&"${LOCK_PROC[1]}"
  # Take the lock (blocks until granted) and emit a sentinel we wait for.
  printf 'SELECT pg_advisory_lock(%s);\n' "$LOCK_KEY" >"/dev/fd/$LOCK_FD"
  printf '\\echo __LOCK_ACQUIRED__\n' >"/dev/fd/$LOCK_FD"
  local line
  while IFS= read -r line <&"${LOCK_PROC[0]}"; do
    case "$line" in
      *__LOCK_ACQUIRED__*) break ;;
    esac
  done
}

release_lock() {
  if [ -n "$LOCK_SESSION_PID" ]; then
    # Explicitly unlock + quit, then close the fd so psql sees EOF and exits.
    printf 'SELECT pg_advisory_unlock(%s);\n\\q\n' "$LOCK_KEY" \
      >"/dev/fd/$LOCK_FD" 2>/dev/null || true
    exec {LOCK_FD}>&- 2>/dev/null || true
    wait "$LOCK_SESSION_PID" 2>/dev/null || true
    LOCK_SESSION_PID=""
  fi
}
trap release_lock EXIT

acquire_lock

# --- create the ledger (idempotent, access-controlled) -----------------------
psql "$DB_URL" -v ON_ERROR_STOP=1 -q <<'SQL'
CREATE SCHEMA IF NOT EXISTS taxflow_internal;
REVOKE ALL ON SCHEMA taxflow_internal FROM anon, authenticated;
CREATE TABLE IF NOT EXISTS taxflow_internal.applied_migrations (
    version    text PRIMARY KEY,
    filename   text NOT NULL,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);
REVOKE ALL ON taxflow_internal.applied_migrations FROM anon, authenticated;
SQL

# --- bootstrap mode: --mark-applied-through ----------------------------------
if [ -n "$MARK_THROUGH" ]; then
  if ! [[ "$MARK_THROUGH" =~ ^[0-9]{3}$ ]]; then
    echo "ERROR: --mark-applied-through expects a 3-digit version (e.g. 040), got '$MARK_THROUGH'." >&2
    exit 1
  fi
  # Validate the target version file exists.
  target_idx=-1
  for i in "${!VERSIONS[@]}"; do
    if [ "$((10#${VERSIONS[$i]}))" -eq "$((10#$MARK_THROUGH))" ]; then
      target_idx=$i
      break
    fi
  done
  if [ "$target_idx" -lt 0 ]; then
    echo "ERROR: no migration file for version '$MARK_THROUGH' in $MIGRATIONS_DIR." >&2
    exit 1
  fi

  # Schema PREFLIGHT: for versions <= 040, verify the key objects actually exist
  # before recording them as applied (never mark an unmigrated schema as done).
  if [ "$((10#$MARK_THROUGH))" -ge 40 ]; then
    echo "Running schema preflight for --mark-applied-through $MARK_THROUGH..."
    missing="$(psql_scalar "
      SELECT string_agg(x, ', ') FROM (
        SELECT 'engagements table' AS x
          WHERE to_regclass('public.engagements') IS NULL
        UNION ALL SELECT 'queries.deleted_at'
          WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='queries' AND column_name='deleted_at')
        UNION ALL SELECT 'queries.edited_at'
          WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='queries' AND column_name='edited_at')
        UNION ALL SELECT 'documents.edited_at'
          WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
            WHERE table_schema='public' AND table_name='documents' AND column_name='edited_at')
      ) t;")"
    if [ -n "$missing" ]; then
      echo "ERROR: schema preflight failed — expected objects missing: $missing" >&2
      echo "       Refusing to mark 001..$MARK_THROUGH as applied against an unmigrated schema." >&2
      exit 1
    fi
  fi

  count=0
  for i in "${!VERSIONS[@]}"; do
    if [ "$((10#${VERSIONS[$i]}))" -le "$((10#$MARK_THROUGH))" ]; then
      psql "$DB_URL" -v ON_ERROR_STOP=1 -q -c \
        "INSERT INTO taxflow_internal.applied_migrations (version, filename, checksum)
         VALUES ('${VERSIONS[$i]}', '${FILES[$i]}', '${SUMS[$i]}')
         ON CONFLICT (version) DO NOTHING;"
      count=$((count + 1))
    fi
  done
  echo "Marked $count migration(s) as applied (through $MARK_THROUGH) without running SQL."
  exit 0
fi

# --- normal mode: apply pending migrations -----------------------------------
# Fetch already-recorded (version -> checksum) into an associative array.
declare -A RECORDED=()
while IFS='|' read -r rec_version rec_sum; do
  [ -z "$rec_version" ] && continue
  RECORDED["$rec_version"]="$rec_sum"
done < <(psql "$DB_URL" -v ON_ERROR_STOP=1 -qtA -F '|' \
  -c "SELECT version, checksum FROM taxflow_internal.applied_migrations;")

declare -a APPLIED=()
for i in "${!VERSIONS[@]}"; do
  version="${VERSIONS[$i]}"
  fname="${FILES[$i]}"
  path="${PATHS[$i]}"
  sum="${SUMS[$i]}"

  if [ -n "${RECORDED[$version]+x}" ]; then
    # Already applied — verify the checksum still matches.
    if [ "${RECORDED[$version]}" != "$sum" ]; then
      echo "ERROR: checksum mismatch for already-applied migration $fname." >&2
      echo "       recorded=${RECORDED[$version]} current=$sum" >&2
      echo "       A shipped migration was edited after being applied — refusing to continue." >&2
      exit 1
    fi
    continue
  fi

  # Apply the DDL + record the ledger row in ONE transaction, so a partial apply
  # is never recorded (both roll back together on any error).
  echo "Applying $fname ..."
  if ! psql "$DB_URL" -v ON_ERROR_STOP=1 --single-transaction \
      -f "$path" \
      -c "INSERT INTO taxflow_internal.applied_migrations (version, filename, checksum)
          VALUES ('$version', '$fname', '$sum');"; then
    echo "ERROR: migration failed and was rolled back: $fname" >&2
    exit 1
  fi
  APPLIED+=("$version")
done

if [ "${#APPLIED[@]}" -eq 0 ]; then
  echo "No pending migrations."
else
  # Join applied versions with ", ".
  joined="$(IFS=', '; echo "${APPLIED[*]}")"
  echo "Applied ${#APPLIED[@]} migration(s): $joined"
fi
