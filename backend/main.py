import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.db.session import init_db
from app.routers.check_in import router as check_in_router
from app.routers.ehr import router as ehr_router
from app.routers.hypothesis import router as hypothesis_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Sukshma-Jignaasa",
    description="AI companion for rare disease pattern detection",
    version="0.2.0",
    lifespan=lifespan,
)

app.include_router(check_in_router)
app.include_router(ehr_router)
app.include_router(hypothesis_router)


@app.get("/health", tags=["Health"])
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
