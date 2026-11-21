#!/bin/bash
# Put the current commit live on the NAS, hands-off.
#
#   tools/adborth/deploy.sh            build what changed, restart, wait, check
#   tools/adborth/deploy.sh --status   what the helper is doing or last did
#   tools/adborth/deploy.sh --update-helper   send the helper its own new code
#   tools/adborth/deploy.sh --timings  how long recent uploads and processing took
#   tools/adborth/deploy.sh --force    deploy even while a video is processing
#   tools/adborth/deploy.sh --all      rebuild both images whatever changed
#
# It also runs on the NAS itself, from the claude-remote gate's "update adborth":
# ADBORTH_SHARE=/share/Container/freeframe and ADBORTH_KEY_FILE=<the helper's key file>.
#
# It copies only the files that changed since the last deploy to the NAS, gives
# the images a new tag (keeping the old compose file as the way back), asks the
# helper on the NAS to build and restart, and waits for the site to answer.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

SHARE="${ADBORTH_SHARE:-/Volumes/container/freeframe}"
HELPER="${ADBORTH_HELPER:-http://192.168.3.210:8399}"
SITE="${ADBORTH_SITE:-https://adborth.stori.cymru}"

call() {  # call <path> <json body>: a signed POST; prints the answer, then the HTTP code
  local path="$1" body="$2" key sig
  # On a Mac the key is in the Keychain. Run on the NAS itself (the gate's
  # "update adborth"), ADBORTH_KEY_FILE names the helper's own key file.
  if [ -n "${ADBORTH_KEY_FILE:-}" ]; then
    key="$(cat "$ADBORTH_KEY_FILE" 2>/dev/null)"
    [ -n "$key" ] || { echo "No deploy key in $ADBORTH_KEY_FILE." >&2; exit 1; }
  else
    key="$(security find-generic-password -s adborth-deploy-key -a adborth -w 2>/dev/null)" \
      || { echo "No deploy key in the Keychain. Run tools/adborth/make-deploy-key.sh once." >&2; exit 1; }
  fi
  sig="$(printf 'POST\n%s\n%s' "$path" "$body" | openssl dgst -sha256 -hmac "$key" -r | cut -d' ' -f1)"
  unset key
  curl -sS -m 30 -X POST -H "X-Signature: $sig" -H 'Content-Type: application/json' \
    --data-binary "$body" -w '\n%{http_code}' "$HELPER$path"
}
stamp() { printf '"ts": %s, "nonce": "%s"' "$(date +%s)" "$(openssl rand -hex 16)"; }
field() { python3 -c 'import json,sys; d=json.loads(sys.argv[1]); v=d.get(sys.argv[2]); print("" if v is None else v)' "$1" "$2"; }

show_status() {
  local out; out="$(call /status "{$(stamp)}")"
  local code="${out##*$'\n'}" body="${out%$'\n'*}"
  [ "$code" = 200 ] || { echo "The helper answered $code: $body"; return 1; }
  python3 - "$body" <<'PY'
import json, sys, time
d = json.loads(sys.argv[1])
when = lambda t: time.strftime('%H:%M:%S', time.localtime(t)) if t else '-'
print(f"busy uploads/transcodes: {d.get('busy')}")
print(f"state: {d['state']}  step: {d['step'] or '-'}  started: {when(d['started'])}  finished: {when(d['finished'])}  ok: {d['ok']}")
print(d['log_tail'][-1500:])
PY
}

MODE=deploy FORCE=false ALL=false
for arg in "$@"; do case "$arg" in
  --status) MODE=status ;; --timings) MODE=timings ;; --update-helper) MODE=update-helper ;; --force) FORCE=true ;; --all) ALL=true ;;
  *) echo "Unknown option $arg"; exit 2 ;;
esac; done
if [ "$MODE" = status ]; then show_status; exit; fi
if [ "$MODE" = timings ]; then
  OUT="$(call /timings "{$(stamp)}")"
  python3 - "${OUT%$'\n'*}" <<'PY'
import json, sys
runs = json.loads(sys.argv[1]).get("runs")
if runs is None:
    sys.exit("The helper could not read the timing log.")
t = lambda s: "-" if s is None else f"{int(s) // 60}m{int(s) % 60:02d}s"
for r in runs:
    line = (f"{r['uploaded_utc']}  {str(r['asset_name'])[:28]:28}  {r['gb']} GB  {r['height'] or '?'}p  "
            f"upload {t(r['upload_s'])}  watchable {t(r['watchable_s'])}  processed {t(r['processing_s'])}  {r['outcome'] or 'running'}")
    if r.get("reprocess_utc"):
        line += f"\n    reprocessed {r['reprocess_utc']} ({r['reprocess_qualities']}): {t(r['reprocess_s'])}  {r['reprocess_outcome'] or 'running'}"
    print(line)
PY
  exit
fi
if [ "$MODE" = update-helper ]; then
  # The helper's own code changed: copy it over and have it start again.
  cp tools/adborth/deployer/server.py "$SHARE/deployer/server.py"
  call /restart "{$(stamp)}" | head -1; sleep 5; show_status; exit
fi

[ -d "$SHARE/src" ] || { echo "The NAS share is not mounted at $SHARE."; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Commit your changes first: the NAS gets exactly what is committed."; exit 1; }
curl -sS -m 10 -o /dev/null "$HELPER/ping" || { echo "The deploy helper is not answering at $HELPER."; exit 1; }

HEAD_SHA="$(git rev-parse --short HEAD)"
LAST="$(head -1 "$SHARE/src/BUILT-FROM.txt" 2>/dev/null || true)"
if [ -n "$LAST" ] && git cat-file -e "$LAST^{commit}" 2>/dev/null; then
  CHANGED="$(git diff --name-only --diff-filter=ACMRT "$LAST" HEAD)"
  GONE="$(git diff --name-only --diff-filter=D "$LAST" HEAD)"
else
  LAST=""; CHANGED="$(git ls-files)"; GONE=""; ALL=true
fi
if [ -z "$CHANGED$GONE" ] && [ "$ALL" = false ]; then echo "Nothing has changed since $LAST."; exit 0; fi

# Which images the change touches. The API image is built from the whole repo
# (apps/api and packages); the site image from apps/web alone.
SERVICES=()
if [ "$ALL" = true ] || printf '%s\n%s\n' "$CHANGED" "$GONE" | grep -qE '^(apps/api/|packages/)'; then SERVICES+=(api); fi
if [ "$ALL" = true ] || printf '%s\n%s\n' "$CHANGED" "$GONE" | grep -qE '^apps/web/'; then SERVICES+=(web); fi
if [ ${#SERVICES[@]} -eq 0 ]; then
  echo "The change touches neither the API nor the site (${LAST:-nothing} -> $HEAD_SHA). Nothing to build."
  printf '%s\n' "$HEAD_SHA" > "$SHARE/src/BUILT-FROM.txt"; exit 0
fi

echo "Copying $(printf '%s\n' "$CHANGED" | grep -c . || true) changed file(s) to the NAS…"
if [ -n "$CHANGED" ]; then
  printf '%s\n' "$CHANGED" | tr '\n' '\0' | xargs -0 git archive HEAD -- | tar -x -C "$SHARE/src"
fi
if [ -n "$GONE" ]; then
  # Files the commit removed: moved aside on the NAS, never deleted from here.
  mkdir -p "$SHARE/src-removed"
  printf '%s\n' "$GONE" | while IFS= read -r f; do
    [ -f "$SHARE/src/$f" ] && mv "$SHARE/src/$f" "$SHARE/src-removed/$(printf '%s' "$f" | tr '/' '_')" || true
  done
fi
printf '%s\n%s\n' "$HEAD_SHA" "$(git branch --show-current) of github.com/storicymru/freeframe" > "$SHARE/src/BUILT-FROM.txt"

# A new tag for what is being rebuilt; the compose file as it was is the way back.
for svc in "${SERVICES[@]}"; do
  CUR="$(grep -m1 -oE "stori/freeframe-$svc:[^ ]+" "$SHARE/docker-compose.yml" | cut -d: -f2)"
  BASE="${CUR%.*}"; N="${CUR##*.}"; NEW="$BASE.$((N + 1))"
  # Kept from the first try only: after a failed build the compose file names
  # images that were never made, and saving that over the way back would lose it.
  [ "${BACKED_UP:-}" = yes ] || { [ -e "$SHARE/docker-compose.before-$HEAD_SHA.yml" ] || cp "$SHARE/docker-compose.yml" "$SHARE/docker-compose.before-$HEAD_SHA.yml"; BACKED_UP=yes; }
  # Written through a copy, not `sed -i`, whose spelling differs between macOS and Linux.
  for f in "$SHARE/docker-compose.yml" "$SHARE/docker-compose.build.yml"; do
    sed "s|stori/freeframe-$svc:$CUR|stori/freeframe-$svc:$NEW|g" "$f" > "$f.new" && cat "$f.new" > "$f"; rm -f "$f.new"
  done
  echo "  $svc: $CUR -> $NEW"
done

LIST="$(printf '"%s",' "${SERVICES[@]}")"
OUT="$(call /deploy "{$(stamp), \"services\": [${LIST%,}], \"force\": $FORCE}")"
CODE="${OUT##*$'\n'}"; BODY="${OUT%$'\n'*}"
if [ "$CODE" != 202 ]; then
  echo "The helper refused ($CODE): $(field "$BODY" error)"
  echo "The new source and tags are on the NAS but nothing was built. Run this again when it is clear, or with --force."
  exit 1
fi
echo "Building ${SERVICES[*]} on the NAS…"
START=$(date +%s)
while :; do
  sleep 10
  OUT="$(call /status "{$(stamp)}")"; BODY="${OUT%$'\n'*}"
  STATE="$(field "$BODY" state)"; STEP="$(field "$BODY" step)"
  printf '\r  %3ss  %s %s        ' "$(( $(date +%s) - START ))" "$STATE" "$STEP"
  [ "$STATE" = running ] || break
done
echo
if [ "$(field "$BODY" ok)" != True ]; then
  echo "The deploy FAILED. The site is still on the previous build unless the restart had begun. Last of the log:"
  field "$BODY" log_tail | tail -40
  echo "To go back: copy docker-compose.before-$HEAD_SHA.yml over docker-compose.yml on the NAS and deploy again."
  exit 1
fi
printf 'Waiting for the site'
for _ in $(seq 1 40); do
  [ "$(curl -s -o /dev/null -m 8 -w '%{http_code}' "$SITE/api/health")" = 200 ] && { echo; echo "Live: $HEAD_SHA (${SERVICES[*]}) in $(( $(date +%s) - START ))s."; exit 0; }
  printf '.'; sleep 5
done
echo; echo "Built and restarted, but $SITE is not answering yet. Check tools/adborth/deploy.sh --status."; exit 1
