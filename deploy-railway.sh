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

echo "⟳  Phase 1 — creating project and services …"

# 1. Create project
railway project create --name "$PROJECT_NAME" 2>/dev/null || true
railway project use "$PROJECT_NAME" 2>/dev/null || true

# 2. Create backend service
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
