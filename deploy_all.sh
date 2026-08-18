#!/usr/bin/env bash
set -Eeuo pipefail

# One-command Ubuntu deployment:
# local folder -> private GitHub repo -> Vercel -> Telegram webhook
#
# Manual Vercel secrets are intentionally limited to FIVE:
#   TELEGRAM_BOT_TOKEN
#   GOOGLE_AI_API_KEY
#   FAL_KEY
#   SUPABASE_DATABASE_URL
#   SUPABASE_SERVICE_ROLE_KEY

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

VERCEL_SCOPE="${VERCEL_SCOPE:-boris-llc}"
REPO_NAME="${REPO_NAME:-ai-video-telegram-bot}"
VERCEL_PROJECT="${VERCEL_PROJECT:-$REPO_NAME}"
GITHUB_VISIBILITY="${GITHUB_VISIBILITY:-private}"
SUPABASE_URL="https://avpkxroflhlifjxfqbqi.supabase.co"

info() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

need_cmd() { command -v "$1" >/dev/null 2>&1; }

install_ubuntu_prereqs() {
  if ! need_cmd apt-get; then
    die "This installer currently targets Ubuntu/Debian (apt-get not found)."
  fi
  local pkgs=()
  for item in git:git curl:curl python3:python3 npm:npm node:nodejs gh:gh; do
    local cmd="${item%%:*}" pkg="${item##*:}"
    need_cmd "$cmd" || pkgs+=("$pkg")
  done
  if ((${#pkgs[@]})); then
    info "Installing missing tools: ${pkgs[*]}"
    sudo apt-get update
    sudo apt-get install -y "${pkgs[@]}"
  fi
}

vc() {
  npx --yes vercel@latest "$@"
}

prompt_secret() {
  local var="$1"
  local label="$2"
  local value=""

  # Do not combine assignment of `var` with indirect expansion.
  # Under `set -u`, `${!var:-}` in the same `local` statement can fail
  # with: "invalid indirect expansion".
  value="${!var-}"

  if [[ -z "$value" ]]; then
    read -r -s -p "$label: " value
    printf '\n'
  fi
  [[ -n "$value" ]] || die "$var cannot be empty"
  printf -v "$var" '%s' "$value"
  export "$var"
}

http_ok() {
  curl -fsS --connect-timeout 10 --max-time 30 "$@" >/dev/null
}

vercel_secret() {
  local key="$1" value="$2" tmp
  tmp="$(mktemp)"
  chmod 600 "$tmp"
  printf '%s' "$value" > "$tmp"
  # --force makes the script safely re-runnable.
  vc env add "$key" production --sensitive --force --scope "$VERCEL_SCOPE" < "$tmp" >/dev/null
  command -v shred >/dev/null 2>&1 && shred -u "$tmp" || rm -f "$tmp"
  ok "Vercel env: $key"
}

cleanup() {
  unset TELEGRAM_BOT_TOKEN GOOGLE_AI_API_KEY FAL_KEY SUPABASE_DATABASE_URL SUPABASE_SERVICE_ROLE_KEY || true
}
trap cleanup EXIT

info "Checking local tools"
install_ubuntu_prereqs
need_cmd git || die "git missing"
need_cmd gh || die "GitHub CLI missing"
need_cmd npm || die "npm missing"
need_cmd python3 || die "python3 missing"

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if (( NODE_MAJOR < 20 )); then
  warn "Node.js $NODE_MAJOR detected. Vercel CLI may require a newer Node release."
  warn "If Vercel CLI refuses to run, update Node.js to 20+ and rerun this script."
fi

python3 -m compileall -q app || die "Python syntax validation failed"
python3 - <<'PY'
import json
json.load(open('vercel.json'))
print('vercel.json: valid')
PY
ok "Source syntax checks passed"

info "GitHub authentication"
if ! gh auth status >/dev/null 2>&1; then
  warn "GitHub login is required once. A browser/device flow will open."
  gh auth login --web --git-protocol https
fi
gh auth status >/dev/null 2>&1 || die "GitHub authentication failed"
GH_USER="$(gh api user --jq .login)"
FULL_REPO="$GH_USER/$REPO_NAME"
ok "GitHub user: $GH_USER"

info "Vercel authentication"
if ! vc whoami >/dev/null 2>&1; then
  warn "Vercel login is required once."
  vc login
fi
VC_USER="$(vc whoami 2>/dev/null | tail -n1)"
ok "Vercel authenticated as ${VC_USER:-user}"

info "Enter only API/Supabase secrets"
prompt_secret TELEGRAM_BOT_TOKEN "Telegram BotFather token"
prompt_secret GOOGLE_AI_API_KEY "Google AI Studio API key"
prompt_secret FAL_KEY "fal.ai API key"
prompt_secret SUPABASE_DATABASE_URL "Supabase Transaction Pooler URI"
prompt_secret SUPABASE_SERVICE_ROLE_KEY "Supabase service_role key"

info "Validating API credentials before deployment"
TG_JSON="$(curl -fsS --max-time 30 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe")" || die "Telegram token validation failed"
python3 - "$TG_JSON" <<'PY'
import json, sys
obj=json.loads(sys.argv[1])
assert obj.get('ok') is True, obj
print('Telegram token: valid')
PY

http_ok "https://generativelanguage.googleapis.com/v1beta/models?key=${GOOGLE_AI_API_KEY}" \
  || die "Google AI Studio key validation failed"
ok "Google AI key valid"

http_ok -H "Authorization: Key ${FAL_KEY}" "https://api.fal.ai/v1/models/pricing?endpoint_id=fal-ai%2Fpixverse%2Fv6%2Ftext-to-video" \
  || die "fal.ai key/pricing validation failed"
ok "fal.ai key valid and pricing API reachable"

SUPABASE_CHECK="${SUPABASE_URL}/rest/v1/project_budget?select=id,spent,reserved,limit&id=eq.1"
http_ok -H "apikey: ${SUPABASE_SERVICE_ROLE_KEY}" \
        -H "Authorization: Bearer ${SUPABASE_SERVICE_ROLE_KEY}" \
        "$SUPABASE_CHECK" || die "Supabase service_role/schema validation failed"
ok "Supabase service_role and production schema valid"

info "Creating/updating Git repository"
if [[ ! -d .git ]]; then
  git init -b main
fi
git branch -M main

if ! git config user.name >/dev/null; then
  git config user.name "$GH_USER"
fi
if ! git config user.email >/dev/null; then
  git config user.email "${GH_USER}@users.noreply.github.com"
fi

if gh repo view "$FULL_REPO" >/dev/null 2>&1; then
  ok "GitHub repository already exists: $FULL_REPO"
else
  if [[ "$GITHUB_VISIBILITY" == "public" ]]; then
    gh repo create "$FULL_REPO" --public --description "Telegram audio-to-AI-video bot: Gemini + fal.ai + Supabase + Vercel"
  else
    gh repo create "$FULL_REPO" --private --description "Telegram audio-to-AI-video bot: Gemini + fal.ai + Supabase + Vercel"
  fi
  ok "Created GitHub repository: $FULL_REPO"
fi

EXPECTED_REMOTE="https://github.com/${FULL_REPO}.git"
if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$EXPECTED_REMOTE"
else
  git remote add origin "$EXPECTED_REMOTE"
fi

git add -A
if ! git diff --cached --quiet; then
  git commit -m "Deploy AI video Telegram bot"
else
  ok "No new Git changes to commit"
fi
git push -u origin main
ok "GitHub push complete: https://github.com/$FULL_REPO"

info "Linking Vercel project in team $VERCEL_SCOPE"
vc link --yes --project "$VERCEL_PROJECT" --scope "$VERCEL_SCOPE"
ok "Vercel project linked: $VERCEL_PROJECT"

# Connect GitHub so future pushes can deploy through Vercel's Git integration.
if vc git connect --yes --scope "$VERCEL_SCOPE"; then
  ok "GitHub connected to Vercel"
else
  warn "Vercel Git integration could not be connected automatically."
  warn "The production CLI deployment below can still succeed; rerun 'npx vercel@latest git connect' later if needed."
fi

info "Uploading exactly five Production environment variables"
vercel_secret TELEGRAM_BOT_TOKEN "$TELEGRAM_BOT_TOKEN"
vercel_secret GOOGLE_AI_API_KEY "$GOOGLE_AI_API_KEY"
vercel_secret FAL_KEY "$FAL_KEY"
vercel_secret SUPABASE_DATABASE_URL "$SUPABASE_DATABASE_URL"
vercel_secret SUPABASE_SERVICE_ROLE_KEY "$SUPABASE_SERVICE_ROLE_KEY"

info "Deploying production to Vercel"
PROD_URL="$(vc deploy --prod --yes --scope "$VERCEL_SCOPE")"
PROD_URL="$(printf '%s\n' "$PROD_URL" | tail -n1 | tr -d '\r')"
[[ "$PROD_URL" == https://* ]] || die "Could not determine Vercel deployment URL: $PROD_URL"
ok "Deployment: $PROD_URL"

# Prefer the stable project alias when Vercel assigned it; otherwise use the immutable deployment URL.
STABLE_URL="https://${VERCEL_PROJECT}.vercel.app"
APP_URL="$PROD_URL"
if http_ok "${STABLE_URL}/health"; then
  APP_URL="$STABLE_URL"
  ok "Stable production URL: $APP_URL"
else
  warn "Stable ${STABLE_URL} was not reachable; Telegram will use the immutable deployment URL."
fi

info "Checking production health"
HEALTH="$(curl -fsS --retry 8 --retry-delay 2 --retry-all-errors "${APP_URL}/health")" \
  || die "Production health endpoint failed"
printf '%s\n' "$HEALTH"
python3 - "$HEALTH" <<'PY'
import json, sys
obj=json.loads(sys.argv[1])
assert obj.get('ok') is True, obj
assert obj.get('configured') is True, obj
assert obj.get('manual_env_count') == 5, obj
print('Production health: PASS')
PY

info "Installing Telegram webhook"
TG_PATH="$(python3 - "$TELEGRAM_BOT_TOKEN" <<'PY'
import hashlib, hmac, sys
secret=sys.argv[1].encode()
print(hmac.new(secret, b'telegram-webhook-v1', hashlib.sha256).hexdigest()[:48])
PY
)"
TG_WEBHOOK_URL="${APP_URL%/}/api/telegram/${TG_PATH}"
SET_WEBHOOK_RESULT="$(curl -fsS --max-time 30 -X POST \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  --data-urlencode "url=${TG_WEBHOOK_URL}" \
  --data-urlencode 'allowed_updates=["message","callback_query"]' \
  --data-urlencode 'drop_pending_updates=false')" || die "Telegram setWebhook failed"
python3 - "$SET_WEBHOOK_RESULT" <<'PY'
import json, sys
obj=json.loads(sys.argv[1])
assert obj.get('ok') is True, obj
print(obj.get('description', 'Webhook configured'))
PY
ok "Telegram webhook installed"

info "Final verification"
WEBHOOK_INFO="$(curl -fsS --max-time 30 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo")"
python3 - "$WEBHOOK_INFO" "$TG_WEBHOOK_URL" <<'PY'
import json, sys
obj=json.loads(sys.argv[1])
expected=sys.argv[2]
assert obj.get('ok') is True, obj
url=(obj.get('result') or {}).get('url')
assert url == expected, (url, expected)
print('Telegram webhook: PASS')
PY

printf '\n\033[1;32mDEPLOY COMPLETE\033[0m\n'
printf 'GitHub:  https://github.com/%s\n' "$FULL_REPO"
printf 'Vercel:  %s\n' "$APP_URL"
printf 'Health:  %s/health\n' "$APP_URL"
printf 'Supabase project: avpkxroflhlifjxfqbqi\n'
printf 'Vercel manual env vars: 5\n'
printf '\nSend /start to your Telegram bot.\n'
