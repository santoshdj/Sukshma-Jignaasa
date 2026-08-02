# deploy-railway.ps1 — Two-phase Railway deployment for Sukshma-Jignaasa
#
# Usage:
#   Phase 1 (first deploy):
#     .\deploy-railway.ps1
#
#   Phase 2 (link frontend → backend URL after both services are live):
#     .\deploy-railway.ps1 -Phase2 -BackendUrl "https://xxx.up.railway.app"
#
# Prerequisites:
#   - railway CLI installed  (npm i -g @railway/cli)
#   - railway login          (run once before this script)
#   - backend\.env           (real secrets — never committed)
#   - GitHub repo pushed     (santoshdj/Sukshma-Jignaasa)

param(
  [switch]$Phase2,
  [string]$BackendUrl = ""
)

$ErrorActionPreference = "Stop"

$GITHUB_REPO  = "santoshdj/Sukshma-Jignaasa"
$PROJECT_NAME = "sukshma-jignaasa"
$BRANCH       = "phase-2-intelligence-layer"

# ── prerequisites ─────────────────────────────────────────────────────────────
function Test-Prerequisites {
  Write-Host "⟳  Checking prerequisites …" -ForegroundColor Cyan

  # git must be present
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git not found. Install from https://git-scm.com/downloads and re-run."
  }
  Write-Host "  ✔  git: $(git --version)"

  # railway CLI — auto-install if missing
  if (-not (Get-Command railway -ErrorAction SilentlyContinue)) {
    Write-Host "  → railway CLI not found — installing …" -ForegroundColor Yellow

    if (Get-Command npm -ErrorAction SilentlyContinue) {
      npm install -g @railway/cli
    } elseif (Get-Command winget -ErrorAction SilentlyContinue) {
      winget install Railway.RailwayCLI --silent
    } else {
      throw "Cannot auto-install railway CLI: npm and winget not found.`nInstall Node.js from https://nodejs.org then run: npm install -g @railway/cli"
    }

    # Refresh PATH so the new binary is found in this session
    $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('PATH', 'User')

    if (-not (Get-Command railway -ErrorAction SilentlyContinue)) {
      throw "railway CLI installed but not found in PATH. Open a new terminal and re-run."
    }
    Write-Host "  ✔  railway CLI installed." -ForegroundColor Green
  } else {
    $ver = railway --version 2>$null
    Write-Host "  ✔  railway CLI: $ver"
  }

  # Verify Railway login
  $whoami = railway whoami 2>&1
  if ($LASTEXITCODE -ne 0 -or $whoami -match 'not logged') {
    Write-Host "  → Not logged in to Railway — launching browser login …" -ForegroundColor Yellow
    railway login
    $whoami = railway whoami 2>&1
  }
  Write-Host "  ✔  Logged in as: $whoami"

  Write-Host "✔  All prerequisites satisfied.`n" -ForegroundColor Green
}

Test-Prerequisites

# ── link to / create Railway project ─────────────────────────────────────────
function Connect-RailwayProject {
  Write-Host "⟳  Linking to Railway project …" -ForegroundColor Cyan

  # Already linked — nothing to do
  $status = railway status 2>&1
  if ($LASTEXITCODE -eq 0 -and $status -notmatch 'not linked') {
    Write-Host "  ✔  Already linked." -ForegroundColor Green
    $status | Select-String -Pattern 'Project|Environment' | ForEach-Object { Write-Host "  $_" }
    Write-Host ""
    return
  }

  Write-Host "  → No project linked. Launching interactive project selector …" -ForegroundColor Yellow
  Write-Host "      Tip: select '$PROJECT_NAME' from the list, or choose 'Create new project'."
  Write-Host ""

  # railway link opens an interactive TUI — user picks or creates a project
  railway link
  if ($LASTEXITCODE -ne 0) {
    throw "railway link exited without selecting a project. Run 'railway link' manually then re-run this script."
  }

  # Confirm the link succeeded
  $status = railway status 2>&1
  if ($LASTEXITCODE -ne 0) {
    throw "Still not linked after railway link. Run it manually and re-run this script."
  }

  Write-Host "  ✔  Project linked successfully.`n" -ForegroundColor Green
}

Connect-RailwayProject

# ── helper: load .env file into hashtable ──────────────────────────────────────
function Read-EnvFile($Path) {
  $vars = @{}
  foreach ($line in Get-Content $Path) {
    if ($line -match '^\s*#' -or $line -match '^\s*$') { continue }
    $kv = $line -split '=', 2
    if ($kv.Length -eq 2) {
      $vars[$kv[0].Trim()] = $kv[1].Trim()
    }
  }
  return $vars
}

# ── Phase 2 ────────────────────────────────────────────────────────────────────
if ($Phase2) {
  if (-not $BackendUrl) {
    Write-Error "Provide -BackendUrl https://your-backend.up.railway.app"
    exit 1
  }

  Write-Host "⟳  Phase 2 — linking frontend → backend …" -ForegroundColor Cyan

  railway variables set "BACKEND_URL=$BackendUrl" --service frontend

  Write-Host "✔  BACKEND_URL=$BackendUrl set on frontend service." -ForegroundColor Green
  Write-Host "✔  Railway will redeploy the frontend automatically." -ForegroundColor Green
  exit 0
}

# ── Phase 1 ────────────────────────────────────────────────────────────────────

if (-not (Test-Path "backend\.env")) {
  Write-Error "backend\.env not found. Copy backend\.env.example and fill in real values."
  exit 1
}

$env_vars = Read-EnvFile "backend\.env"

Write-Host "⟳  Phase 1 — configuring services …" -ForegroundColor Cyan

# 1. Backend service
Write-Host "  → Creating backend service …"
railway service create backend --source github --repo $GITHUB_REPO --branch $BRANCH 2>$null; $true

Write-Host "  → Setting backend environment variables …"
railway variables set `
  "ANTHROPIC_API_KEY=$($env_vars['ANTHROPIC_API_KEY'])" `
  "MEDBLOCKS_API_KEY=$($env_vars['MEDBLOCKS_API_KEY'])" `
  "MEDBLOCKS_FHIR_BASE_URL=$($env_vars['MEDBLOCKS_FHIR_BASE_URL'])" `
  "MEDBLOCKS_FHIR_BEARER_TOKEN=$($env_vars['MEDBLOCKS_FHIR_BEARER_TOKEN'])" `
  --service backend

Write-Host "  ✔  Backend service configured." -ForegroundColor Green

# 3. Frontend service
Write-Host "  → Creating frontend service …"
railway service create frontend --source github --repo $GITHUB_REPO --branch $BRANCH 2>$null; $true

Write-Host "  → Setting frontend environment variables …"
railway variables set `
  "NEXT_PUBLIC_APP_NAME=Sukshma-Jignaasa" `
  "BACKEND_URL=http://localhost:8000" `
  --service frontend

Write-Host "  ✔  Frontend service configured." -ForegroundColor Green

Write-Host ""
Write-Host "✅  Phase 1 complete." -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Go to railway.app → open the '$PROJECT_NAME' project"
Write-Host "  2. For EACH service: Settings → Source → Root Directory"
Write-Host "       backend  → /backend"
Write-Host "       frontend → /frontend"
Write-Host "  3. Trigger a deploy for both services."
Write-Host "  4. Once the backend URL is live, run Phase 2:"
Write-Host "       .\deploy-railway.ps1 -Phase2 -BackendUrl 'https://YOUR-BACKEND.up.railway.app'"
