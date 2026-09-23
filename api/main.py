from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.config import DATA_DIR, WEB_DIST
from api.db import init_db
from api.routes import router

app = FastAPI(title="hackalem")


@app.on_event("startup")
def _startup() -> None:
    init_db()


# Mount order is load-bearing: a "/" catch-all StaticFiles mount registered
# before the router would swallow every request, including /api/*, before it
# ever reaches our routes. So: routes first, then /files, then the "/" web
# mount last.

app.include_router(router, prefix="/api")


@app.get("/health")
def health() -> dict:
    return {"ok": True}


app.mount("/files", StaticFiles(directory=DATA_DIR), name="files")

# Mount web/dist LAST, and only if it exists, else the app 500s before the
# first frontend build has happened.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
