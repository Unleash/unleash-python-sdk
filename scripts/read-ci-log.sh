#!/usr/bin/env bash
#
# ci-log — fetch a GitHub Actions job log with `gh` and print an LLM-friendly
#          version to stdout.
#
# Cleanups applied to the raw log:
#   * per-line ISO timestamps removed        (~30 tokens/line saved)
#   * ANSI colour escapes removed
#   * ##[group]/##[endgroup] turned into plain section markers
#   * ##[error]/##[warning]/##[notice] turned into ERROR:/WARN:/NOTE:
#   * ##[debug] lines and runs of blank lines dropped
#   * a header with job status + per-step conclusions is prepended
#   * every ##[error] line is hoisted into an "Errors" section up top
#
set -euo pipefail

PROG=${0##*/}

usage() {
  cat <<EOF
Usage:
  $PROG <job-url|run-url> [options]
  $PROG -R <owner/repo> --run <run-id> [--job <job-id>] [options]

Options:
  --all               Given a run with no job id, include every job instead of
                      only the failed ones.
  --tail N            Print only the last N lines of each job's log body.
  --errors-only       Print the header + error lines only; skip the log body.
  --keep-timestamps   Keep the per-line ISO timestamps.
  --raw               No cleanup; dump the log exactly as GitHub returns it.
  -h, --help          This message.

Examples:
  $PROG "https://github.com/Unleash/unleash-python-sdk/actions/runs/34473205522/job/102857715337?pr=424"
  $PROG "https://github.com/Unleash/unleash-python-sdk/actions/runs/34473205522" --tail 200
  $PROG -R Unleash/unleash-python-sdk --run 34473205522 --errors-only
EOF
}

die() { printf '%s: %s\n' "$PROG" "$*" >&2; exit 1; }

# ---------------------------------------------------------------- args ------
REPO="" RUN_ID="" JOB_ID=""
ALL=0 TAIL=0 ERRORS_ONLY=0 KEEP_TS=0 RAW=0

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)          usage; exit 0 ;;
    -R|--repo)          REPO="${2:?}"; shift 2 ;;
    --run)              RUN_ID="${2:?}"; shift 2 ;;
    --job)              JOB_ID="${2:?}"; shift 2 ;;
    --all)              ALL=1; shift ;;
    --tail)             TAIL="${2:?}"; shift 2 ;;
    --errors-only)      ERRORS_ONLY=1; shift ;;
    --keep-timestamps)  KEEP_TS=1; shift ;;
    --raw)              RAW=1; shift ;;
    -*)                 die "unknown option: $1" ;;
    *)
      # A URL, or a bare run id.
      if [[ "$1" =~ github\.com/([^/]+)/([^/]+)/actions/runs/([0-9]+)(/job/([0-9]+))? ]]; then
        REPO="${BASH_REMATCH[1]}/${BASH_REMATCH[2]}"
        RUN_ID="${BASH_REMATCH[3]}"
        JOB_ID="${BASH_REMATCH[5]:-}"
      elif [[ "$1" =~ ^[0-9]+$ ]]; then
        RUN_ID="$1"
      else
        die "can't parse '$1' as a run/job URL or run id"
      fi
      shift ;;
  esac
done

command -v gh >/dev/null || die "gh is not installed (https://cli.github.com)"
[ -n "$RUN_ID" ] || [ -n "$JOB_ID" ] || { usage >&2; exit 2; }

if [ -z "$REPO" ]; then
  REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null) \
    || die "no repo given and cwd is not a GitHub repo; use -R owner/repo"
fi

# ------------------------------------------------------------- helpers ------
epoch() { # ISO8601 -> unix seconds, GNU date then BSD date
  local ts="${1:-}"
  [ -n "$ts" ] && [ "$ts" != "null" ] || return 0
  date -u -d "$ts" +%s 2>/dev/null && return 0
  date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "$ts" +%s 2>/dev/null || true
}

human() { # seconds -> 1m32s
  local s="${1:-}"
  [ -n "$s" ] || return 0
  if [ "$s" -ge 60 ]; then printf '%dm%02ds' $((s / 60)) $((s % 60));
  else printf '%ds' "$s"; fi
}

duration() { # start end -> human
  local a b
  a=$(epoch "${1:-}") b=$(epoch "${2:-}")
  [ -n "$a" ] && [ -n "$b" ] || return 0
  human $((b - a))
}

# The formatter. Reads a raw job log on stdin, writes the cleaned log.
clean_log() {
  awk -v keep_ts="$KEEP_TS" -v tsv="${1:-0}" '
    function flush_blank() { if (pending && seen) { print ""; } pending = 0 }
    {
      line = $0
      sub(/\r$/, "", line)

      # `gh run view --log` prefixes: <job>\t<step>\t<timestamp>\t<text>
      if (tsv) sub(/^[^\t]*\t[^\t]*\t/, "", line)

      gsub(/\033\[[0-9;?]*[a-zA-Z]/, "", line)          # ANSI SGR / cursor
      gsub(/\033\][^\007]*\007/, "", line)              # OSC sequences

      if (!keep_ts)
        sub(/^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]\.[0-9]+Z ?/, "", line)

      if (line ~ /^##\[debug\]/) next
      if (line ~ /^##\[endgroup\]/) next
      if (line ~ /^##\[group\]/) {
        sub(/^##\[group\]/, "", line)
        if (seen) print ""
        print "----- " line
        seen = 1; pending = 0
        next
      }
      sub(/^##\[error\]/,   "ERROR: ", line)
      sub(/^##\[warning\]/, "WARN: ",  line)
      sub(/^##\[notice\]/,  "NOTE: ",  line)
      sub(/^##\[(section|command|endgroup)\]/, "", line)

      if (line ~ /^[[:space:]]*$/) { pending = 1; next }   # collapse blank runs
      flush_blank()
      print line
      seen = 1
    }
  '
}

fetch_log() { # job_id -> raw log on stdout; echoes "tsv" marker on fd 3 if fallback
  local job="$1" out
  if out=$(gh api "repos/$REPO/actions/jobs/$job/logs" 2>/dev/null); then
    printf '%s\n' "$out"; return 0
  fi
  # Fallback: works for in-progress jobs and some retention edge cases.
  if out=$(gh run view --repo "$REPO" --job "$job" --log 2>/dev/null); then
    printf '%s\n' "$out"; echo tsv >&3; return 0
  fi
  return 1
}

emit_job() {
  local job="$1" meta name status conclusion started completed url attempt workflow sha

  meta=$(gh api "repos/$REPO/actions/jobs/$job" \
    --jq '[.name, .status, .conclusion // "", .started_at // "", .completed_at // "",
           .html_url, .run_attempt // "", .workflow_name // "", .head_sha // ""]
          | @tsv') || die "cannot read job $job in $REPO"
  IFS=$'\t' read -r name status conclusion started completed url attempt workflow sha <<<"$meta"

  echo   "==================================================================="
  printf '# CI job: %s\n' "$name"
  printf 'repo:     %s\n' "$REPO"
  printf 'workflow: %s\n' "${workflow:-?}"
  printf 'run:      %s (attempt %s)   job: %s\n' "$RUN_ID" "${attempt:-1}" "$job"
  printf 'status:   %s / %s\n' "$status" "${conclusion:-in_progress}"
  [ -n "$started" ] && printf 'started:  %s   duration: %s\n' "$started" "$(duration "$started" "$completed")"
  [ -n "$sha" ] && printf 'sha:      %s\n' "$sha"
  printf 'url:      %s\n\n' "$url"

  echo "## Steps"
  gh api "repos/$REPO/actions/jobs/$job" \
    --jq '.steps[]? | [.number, .conclusion // .status, .name, .started_at // "", .completed_at // ""] | @tsv' \
  | while IFS=$'\t' read -r n c sname sstart send; do
      local mark
      case "$c" in
        success)   mark="ok  " ;;
        failure)   mark="FAIL" ;;
        cancelled) mark="canc" ;;
        skipped)   mark="skip" ;;
        *)         mark="$c" ;;
      esac
      printf '  %2s [%s] %s %s\n' "$n" "$mark" "$sname" "$(duration "$sstart" "$send")"
    done
  echo

  local raw tsv=0
  raw=$( { fetch_log "$job" 3>/tmp/.cilog.$$ ; } ) || {
    echo "(log unavailable — expired, or the job has not started)"; echo; return 0
  }
  [ -s "/tmp/.cilog.$$" ] && tsv=1
  rm -f "/tmp/.cilog.$$"

  if [ "$RAW" = 1 ]; then
    echo "## Log (raw)"
    printf '%s\n' "$raw"
    return 0
  fi

  local body errors
  body=$(printf '%s\n' "$raw" | clean_log "$tsv")
  errors=$(printf '%s\n' "$body" | grep -E '^(ERROR|WARN): ' | head -n 50 || true)

  if [ -n "$errors" ]; then
    echo "## Errors and warnings"
    printf '%s\n\n' "$errors"
  fi

  [ "$ERRORS_ONLY" = 1 ] && return 0

  if [ "$TAIL" -gt 0 ]; then
    printf '## Log (last %s lines)\n' "$TAIL"
    printf '%s\n' "$body" | tail -n "$TAIL"
  else
    echo "## Log"
    printf '%s\n' "$body"
  fi
  echo
}

# ---------------------------------------------------------------- main ------
if [ -n "$JOB_ID" ]; then
  [ -n "$RUN_ID" ] || RUN_ID=$(gh api "repos/$REPO/actions/jobs/$JOB_ID" --jq .run_id)
  emit_job "$JOB_ID"
else
  filter='.jobs[]'
  [ "$ALL" = 1 ] || filter='.jobs[] | select(.conclusion == "failure" or .conclusion == "cancelled" or .status != "completed")'
  mapfile -t jobs < <(gh api --paginate "repos/$REPO/actions/runs/$RUN_ID/jobs" --jq "$filter | .id")
  if [ "${#jobs[@]}" -eq 0 ]; then
    echo "Run $RUN_ID in $REPO has no failed jobs. Re-run with --all to see them anyway."
    exit 0
  fi
  for j in "${jobs[@]}"; do emit_job "$j"; done
fi
