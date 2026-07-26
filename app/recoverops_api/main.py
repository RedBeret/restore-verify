from __future__ import annotations

import os
from typing import Any

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

SERVICE_NAME = os.getenv("SERVICE_NAME", "unknown")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://recoverops@localhost/recoverops")

app = FastAPI(title="restore-verify API", version="1.0.0")


def database_summary() -> dict[str, Any]:
    with (
        psycopg.connect(DATABASE_URL, connect_timeout=2) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT to_regclass('public.assets') IS NOT NULL")
        schema_ready = bool(cursor.fetchone()[0])
        if not schema_ready:
            raise RuntimeError("recoverops schema is not available")
        cursor.execute("SELECT count(*) FROM assets")
        assets = int(cursor.fetchone()[0])
        cursor.execute("SELECT count(*) FROM maintenance_events")
        events = int(cursor.fetchone()[0])
    return {"assets": assets, "maintenance_events": events}


@app.get("/")
def root() -> dict[str, str]:
    return {"service": SERVICE_NAME, "project": "restore-verify"}


@app.get("/health", response_model=None)
def health() -> dict[str, Any] | JSONResponse:
    try:
        summary = database_summary()
    except Exception as exc:  # noqa: BLE001 - health must convert dependency failure to 503
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "service": SERVICE_NAME, "error": str(exc)},
        )
    return {"status": "healthy", "service": SERVICE_NAME, **summary}


@app.get("/summary", response_model=None)
def summary() -> dict[str, Any] | JSONResponse:
    return health()
