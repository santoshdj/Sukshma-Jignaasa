import uvicorn
from fastapi import FastAPI

from app.routers.check_in import router as check_in_router

app = FastAPI(
    title="Sukshma-Jignaasa",
    description="AI companion for rare disease pattern detection",
    version="0.1.0",
)

app.include_router(check_in_router)


@app.get("/health", tags=["Health"])
def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
