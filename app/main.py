"""FastAPI app. Binds to localhost by default; see DEPLOYMENT.md."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import Engine, SessionError
from .providers import Provider, provider_from_env
from .storage import Storage
from .summary import to_markdown

STATIC = Path(__file__).resolve().parent.parent / "static"


class StartReq(BaseModel):
    title: str = ""
    profile: str = "meeting"
    mode: str = "hold"
    record_audio: bool = False
    consent: dict = Field(default_factory=dict)
    settings: dict | None = None


class UttReq(BaseModel):
    text: str
    speaker: str | None = None
    ts_ms: int | None = None
    user_speaking: bool = False
    source: str = "typed"


class CallReq(BaseModel):
    text: str | None = None


class SettingsReq(BaseModel):
    mode: str | None = None
    settings: dict | None = None


class ActReq(BaseModel):
    action: str | None = None
    feedback: str | None = None


class DocReq(BaseModel):
    name: str
    text: str
    session_id: str | None = None


def create_app(data_dir: str | None = None, provider: Provider | None = None) -> FastAPI:
    data = Path(data_dir or os.environ.get("COMPANION_DATA", "data"))
    storage = Storage(data / "companion.db", data / "audio")
    days = int(os.environ.get("COMPANION_RETENTION_DAYS", "0"))
    if days > 0:
        storage.purge_older_than(days)
    engine = Engine(storage, provider or provider_from_env())
    app = FastAPI(title="Proactive AI Companion", version="0.1.0")
    app.state.engine = engine

    @app.exception_handler(SessionError)
    async def _err(_, e: SessionError):
        return JSONResponse({"detail": e.msg}, status_code=e.code)

    @app.get("/api/health")
    def health():
        return {"ok": True, "provider": engine.provider.describe(), "retention_days": days}

    @app.post("/api/sessions", status_code=201)
    def start(r: StartReq):
        return engine.start(r.title, r.profile, r.mode, r.consent, r.record_audio, r.settings)

    @app.get("/api/sessions")
    def sessions(q: str | None = None):
        return storage.list_sessions(q)

    @app.get("/api/sessions/{sid}")
    def get(sid: str):
        s = engine._session(sid, need_active=False)
        return {"session": s, "utterances": storage.utterances(sid), "interventions": storage.interventions(sid)}

    @app.post("/api/sessions/{sid}/utterances")
    def utt(sid: str, r: UttReq):
        return engine.ingest(sid, r.text, r.speaker, r.ts_ms, r.user_speaking, r.source)

    @app.post("/api/sessions/{sid}/call")
    def call(sid: str, r: CallReq):
        return engine.call(sid, r.text)

    @app.patch("/api/sessions/{sid}/settings")
    def settings(sid: str, r: SettingsReq):
        return engine.update_settings(sid, r.mode, r.settings)

    for _name, _status in (("pause", "paused"), ("resume", "active"), ("stop", "stopped")):
        app.add_api_route(f"/api/sessions/{{sid}}/{_name}", (lambda st: lambda sid: engine.set_status(sid, st))(_status),
                          methods=["POST"], name=_name)

    @app.post("/api/interventions/{iid}/act")
    def act(iid: str, r: ActReq):
        return engine.act(iid, r.action, r.feedback)

    @app.get("/api/sessions/{sid}/summary")
    def summary(sid: str):
        return engine.summary(sid)

    @app.get("/api/sessions/{sid}/cost")
    def cost(sid: str):
        return engine.cost(sid)

    @app.get("/api/sessions/{sid}/metrics")
    def metrics(sid: str):
        engine._session(sid, need_active=False)
        lat = sorted(u["proc_ms"] for u in storage.utterances(sid) if u["proc_ms"] is not None)
        pct = lambda p: lat[min(int(len(lat) * p), len(lat) - 1)] if lat else None
        ivs = storage.interventions(sid)
        fb = [i["feedback"] for i in ivs if i["feedback"]]
        return {"n": len(lat), "server_processing_ms_p50": pct(0.5), "server_processing_ms_p95": pct(0.95),
                "note": "Server-side processing only; excludes STT and network latency.",
                "interventions": len(ivs), "dismissed": sum(i["status"] == "dismissed" for i in ivs),
                "useful": fb.count("useful"), "not_useful": fb.count("not_useful")}

    @app.get("/api/sessions/{sid}/export")
    def export(sid: str, format: str = "md"):
        s = engine._session(sid, need_active=False)
        utts, ivs = storage.utterances(sid), storage.interventions(sid)
        sm = engine.summary(sid, persist=False)
        if format == "json":
            body = {"session": s, "utterances": utts, "events": storage.events(sid), "interventions": ivs, "summary": sm}
            return Response(json.dumps(body, ensure_ascii=False, indent=2), media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="session-{sid}.json"'})
        if format == "md":
            return PlainTextResponse(to_markdown(s, utts, sm, ivs), headers={"Content-Disposition": f'attachment; filename="session-{sid}.md"'})
        raise HTTPException(422, "format must be md|json (PDF export is not implemented)")

    @app.delete("/api/sessions/{sid}", status_code=204)
    def delete(sid: str):
        engine.states.pop(sid, None)
        if not storage.delete_session(sid):
            raise HTTPException(404, "session not found")

    @app.post("/api/sessions/{sid}/audio", status_code=201)
    async def audio(sid: str, request: Request):
        s = engine._session(sid, need_active=False)
        if not s["record_audio"]:
            raise HTTPException(403, "audio recording was not enabled for this session")
        body = await request.body()
        if not body or len(body) > 200 * 1024 * 1024:
            raise HTTPException(422, "empty or too large")
        ext = "mp4" if "mp4" in request.headers.get("content-type", "") else "webm"
        p = storage.audio_dir / f"{sid}.{ext}"
        p.write_bytes(body)
        storage.update_session(sid, audio_path=str(p))
        return {"bytes": len(body)}

    @app.get("/api/sessions/{sid}/audio")
    def get_audio(sid: str):
        s = engine._session(sid, need_active=False)
        if not s["audio_path"] or not Path(s["audio_path"]).exists():
            raise HTTPException(404, "no audio")
        return FileResponse(s["audio_path"])

    @app.post("/api/documents", status_code=201)
    def add_doc(r: DocReq):
        if not r.text.strip():
            raise HTTPException(422, "empty document")
        return storage.add_document(r.name, r.text, r.session_id)

    @app.get("/api/documents")
    def docs(session_id: str | None = None):
        return [{k: d[k] for k in ("id", "name", "session_id")} for d in storage.documents(session_id)]

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def get_app() -> FastAPI:  # uvicorn --factory app.main:get_app
    return create_app()
