import logging
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)

from app.db.session import init_db
from app.routers.appointment_prep import router as appointment_prep_router
from app.routers.check_in import router as check_in_router
from app.routers.clinical_report import router as clinical_report_router
from app.routers.ehr import router as ehr_router
from app.routers.hypothesis import router as hypothesis_router
from app.routers.users import router as users_router
from app.utils.config import get_settings

_REQUIRED_SETTINGS = {
    "medblocks_api_key": "MEDBLOCKS_API_KEY — obtain from https://app.medblocks.com/settings/api-keys",
    "medblocks_fhir_bearer_token": "MEDBLOCKS_FHIR_BEARER_TOKEN — obtain from https://app.medblocks.com/settings/api-keys",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    missing = [
        f"{env_name} ({hint})"
        for attr, (env_name, hint) in ((k, (k.upper(), v)) for k, v in _REQUIRED_SETTINGS.items())
        if not getattr(settings, attr, None)
    ]
    if missing:
        raise RuntimeError(
            "Missing required environment variables — set them in backend/.env:\n"
            + "\n".join(f"  {m}" for m in missing)
        )
    init_db()
    yield


app = FastAPI(
    title="Sukshma-Jignaasa",
    description="AI companion for rare disease pattern detection",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — allow the frontend origin (set FRONTEND_URL in Railway env vars).
# Falls back to localhost for local development.
_allowed_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if _frontend_url := os.getenv("FRONTEND_URL"):
    _allowed_origins.append(_frontend_url.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(appointment_prep_router)
app.include_router(check_in_router)
app.include_router(clinical_report_router)
app.include_router(ehr_router)
app.include_router(hypothesis_router)
app.include_router(users_router)


@app.get("/health", tags=["Health"])
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
