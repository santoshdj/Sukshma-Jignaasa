#!/usr/bin/env bash
# deploy-railway.sh — Two-phase Railway deployment for Sukshma-Jignaasa
#
# Usage:
#   Phase 1 (first deploy):
#     ./deploy-railway.sh
#
#   Phase 2 (link frontend → backend URL after both services are live):
#     ./deploy-railway.sh --phase2 --backend-url https://xxx.up.railway.app
#
# Prerequisites:
#   - railway CLI installed  (npm i -g @railway/cli)
#   - railway login          (run once before this script)
#   - backend/.env           (real secrets — never committed)
#   - GitHub repo pushed     (santoshdj/Sukshma-Jignaasa)

set -euo pipefail

GITHUB_REPO="santoshdj/Sukshma-Jignaasa"
PROJECT_NAME="sukshma-jignaasa"
RAILWAY_API="https://backboard.railway.app/graphql/v2"

# ── prerequisites ─────────────────────────────────────────────────────────────
check_prerequisites() {
  echo "⟳  Checking prerequisites …"

  # Tools that must exist and cannot be auto-installed
  local missing=()
  for tool in git curl python3; do
    if ! command -v "$tool" &>/dev/null; then
      missing+=("$tool")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "❌  Missing required tools: ${missing[*]}"
    echo "    Install them with your system package manager and re-run."
    exit 1
  fi

  # railway CLI — auto-install if missing
  if ! command -v railway &>/dev/null; then
    echo "  → railway CLI not found — installing …"
    if command -v npm &>/dev/null; then
      npm install -g @railway/cli
    elif command -v brew &>/dev/null; then
      brew install railway
    else
      echo "❌  Cannot auto-install railway CLI: npm and brew not found."
      echo "    Install Node.js (https://nodejs.org) then run: npm install -g @railway/cli"
      exit 1
    fi
    echo "  ✔  railway CLI installed."
  else
    echo "  ✔  railway CLI: $(railway --version 2>/dev/null || echo 'found')"
  fi

  # Verify railway session
  if ! railway whoami &>/dev/null 2>&1; then
    echo "  → Not logged in to Railway — launching browser login …"
    railway login
  fi
  echo "  ✔  Logged in as: $(railway whoami 2>/dev/null)"

  echo "✔  All prerequisites satisfied."
  echo ""
}

check_prerequisites

# ── link to / create Railway project ─────────────────────────────────────────
link_or_create_project() {
  echo "⟳  Linking to Railway project …"

  # Already linked — nothing to do
  if railway status &>/dev/null 2>&1; then
    local info
    info=$(railway status 2>/dev/null | grep -iE 'Project|Environment' || echo "  (project info unavailable)")
    echo "  ✔  Already linked."
    echo "$info"
    echo ""
    return 0
  fi

  echo "  → No project linked. Launching interactive project selector …"
  echo "      Tip: select '$PROJECT_NAME' from the list, or choose \"Create new project\"."
  echo ""

  # railway link opens an interactive TUI — user picks or creates a project
  if ! railway link; then
    echo "❌  railway link exited without selecting a project."
    echo "    Run \"railway link\" manually, then re-run this script."
    exit 1
  fi

  # Confirm the link succeeded
  if ! railway status &>/dev/null 2>&1; then
    echo "❌  Still not linked after railway link. Run it manually and re-run this script."
    exit 1
  fi

  echo "  ✔  Project linked successfully."
  echo ""
}

link_or_create_project

# ── helper: Railway GraphQL call ───────────────────────────────────────────────
railway_gql() {
  local query="$1"
  local token
  token=$(railway whoami --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])" 2>/dev/null || true)

  if [[ -z "$token" ]]; then
    echo "❌  Run 'railway login' first." >&2
    exit 1
  fi

  curl -s -X POST "$RAILWAY_API" \
    -H "Authorization: Bearer $token" \
    -H "Content-Type: application/json" \
    -d "$query"
}

# ── Phase 2 ────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--phase2" ]]; then
  BACKEND_URL="${3:-}"
  if [[ -z "$BACKEND_URL" ]]; then
    echo "Usage: $0 --phase2 --backend-url https://your-backend.up.railway.app"
    exit 1
  fi

  echo "⟳  Phase 2 — linking frontend → backend …"

  # Set BACKEND_URL on the frontend service (triggers redeploy)
  railway variables set BACKEND_URL="$BACKEND_URL" --service frontend

  echo "✔  BACKEND_URL=$BACKEND_URL set on frontend service."
  echo "✔  Railway will redeploy the frontend automatically."
  exit 0
fi

# ── Phase 1 ────────────────────────────────────────────────────────────────────

# Load backend secrets from local .env (never hardcode)
if [[ ! -f backend/.env ]]; then
  echo "❌  backend/.env not found. Copy backend/.env.example and fill in real values."
  exit 1
fi
source backend/.env

echo "⟳  Phase 1 — configuring services …"

# 1. Create backend service
echo "  → Creating backend service …"
railway service create backend --source github --repo "$GITHUB_REPO" \
  --branch phase-2-intelligence-layer 2>/dev/null || true

# Set root directory for backend (Railway CLI v3 / GraphQL)
PROJECT_ID=$(railway status --json 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['projectId'])" 2>/dev/null || echo "")
if [[ -n "$PROJECT_ID" ]]; then
  echo "  → Setting root directory for backend …"
  railway_gql "{\"query\":\"mutation { serviceInstanceUpdate(serviceId: \\\"backend\\\", input: { rootDirectory: \\\"/backend\\\" }) { id } }\"}" > /dev/null
fi

# Set backend env vars
railway variables set \
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  MEDBLOCKS_API_KEY="${MEDBLOCKS_API_KEY:-}" \
  MEDBLOCKS_FHIR_BASE_URL="${MEDBLOCKS_FHIR_BASE_URL:-}" \
  MEDBLOCKS_FHIR_BEARER_TOKEN="${MEDBLOCKS_FHIR_BEARER_TOKEN:-}" \
  --service backend

echo "  ✔  Backend service configured."

# 3. Create frontend service
echo "  → Creating frontend service …"
railway service create frontend --source github --repo "$GITHUB_REPO" \
  --branch phase-2-intelligence-layer 2>/dev/null || true

if [[ -n "$PROJECT_ID" ]]; then
  echo "  → Setting root directory for frontend …"
  railway_gql "{\"query\":\"mutation { serviceInstanceUpdate(serviceId: \\\"frontend\\\", input: { rootDirectory: \\\"/frontend\\\" }) { id } }\"}" > /dev/null
fi

# Set frontend env vars
railway variables set \
  NEXT_PUBLIC_APP_NAME="Sukshma-Jignaasa" \
  BACKEND_URL="http://localhost:8000" \
  --service frontend

echo "  ✔  Frontend service configured."

echo ""
echo "✅  Phase 1 complete."
echo ""
echo "Next steps:"
echo "  1. Go to railway.app → open the project"
echo "  2. For EACH service: Settings → Source → Root Directory"
echo "     backend  → /backend"
echo "     frontend → /frontend"
echo "  3. Trigger a deploy for both services."
echo "  4. Once the backend URL is live, run Phase 2:"
echo "     ./deploy-railway.sh --phase2 --backend-url https://YOUR-BACKEND.up.railway.app"
