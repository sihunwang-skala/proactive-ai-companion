"""Session engine: ingest -> detect -> policy -> respond -> persist. Event-driven; LLM only when gated in."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import events as E
from . import knowledge as kb
from . import policy as P
from .i18n import tr
from .providers import Provider, ProviderError
from .storage import Storage
from .summary import build_summary, fmt_ts

MODES = ("hold", "called_on", "interject")
PROFILES = ("meeting", "learning", "work")


class SessionError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code, self.msg = code, msg


@dataclass
class State:
    facts: dict = field(default_factory=dict)
    seen: set = field(default_factory=set)
    delivered_ms: list = field(default_factory=list)
    seq: int = 0
    tokens: int = 0
    cache: dict = field(default_factory=dict)
    provider_errors: int = 0


class Engine:
    def __init__(self, storage: Storage, provider: Provider):
        self.db, self.provider = storage, provider
        self.states: dict[str, State] = {}

    # ------------------------------------------------------------------ sessions
    def start(self, title, profile, mode, consent, record_audio, settings) -> dict:
        if not consent or not consent.get("recording_consent_confirmed"):
            raise SessionError(400, "Explicit consent is required to start a session (recording_consent_confirmed=true).")
        if profile not in PROFILES or mode not in MODES:
            raise SessionError(422, "invalid profile or mode")
        cfg = {**P.DEFAULT_SETTINGS, **(settings or {})}
        if profile == "learning" and settings is not None and "socratic" not in settings:
            cfg["socratic"] = False
        consent = {**consent, "confirmed_at": time.time(), "cloud_processing": self.provider.is_cloud}
        return self.db.create_session(title or "Untitled session", profile, mode, cfg, consent, record_audio)

    def _session(self, sid, need_active=True) -> dict:
        s = self.db.get_session(sid)
        if not s:
            raise SessionError(404, "session not found")
        if need_active and s["status"] != "active":
            raise SessionError(409, f"session is {s['status']}")
        return s

    def set_status(self, sid, status):
        s = self._session(sid, need_active=False)
        if s["status"] == "stopped":
            raise SessionError(409, "session already stopped")
        if status == "active" and s["status"] != "paused":
            raise SessionError(409, "only paused sessions can resume")
        self.db.update_session(sid, status=status, **({"ended_at": time.time()} if status == "stopped" else {}))
        if status == "stopped":
            self.db.update_session(sid, summary=self.summary(sid, persist=False))
        return self.db.get_session(sid)

    def update_settings(self, sid, mode=None, settings=None):
        s = self._session(sid, need_active=False)
        if mode:
            if mode not in MODES:
                raise SessionError(422, "invalid mode")
            self.db.update_session(sid, mode=mode)
        if settings:
            self.db.update_session(sid, settings={**s["settings"], **settings})
        return self.db.get_session(sid)

    # ------------------------------------------------------------------ state
    def _state(self, sid) -> State:
        if sid in self.states:
            return self.states[sid]
        st = State()
        utts = self.db.utterances(sid)
        st.seq = len(utts)
        for u in utts:
            for f in kb.extract_numeric_facts(u["text"]):
                st.facts[(f["subj"], f["unit"])] = {"value": f["value"], "raw": f["raw"], "utt_id": u["id"], "ts_ms": u["ts_ms"]}
        for ev in self.db.events(sid):
            fp = (ev["payload"] or {}).get("fingerprint")
            if fp and (ev["payload"].get("decision") or {}).get("action") != "drop":
                st.seen.add(fp)
        for iv in self.db.interventions(sid):
            if iv["status"] in ("delivered", "approved") and iv["trigger"] == "auto":
                st.delivered_ms.append(iv["ts_ms"])
        for u in self.db.usage(sid):
            st.tokens += u["tokens_in"] + u["tokens_out"]
        self.states[sid] = st
        return st

    # ------------------------------------------------------------------ answering
    def _answer(self, sid, st, question, settings, allow_llm) -> dict | None:
        hits = kb.retrieve(question, self.db.documents(sid))
        if hits:
            h = hits[0]
            return {"text": tr(settings.get("lang", "en"), "from_doc", doc=h["doc"], p=h["passage"]), "confidence": round(min(0.9, 0.5 + h["score"] * 0.5), 2),
                    "evidence": [{"kind": "user_document", "source": x["doc"], "quote": x["passage"], "score": x["score"]} for x in hits],
                    "origin": "local_retrieval"}
        if not (allow_llm and self.provider.available):
            return None
        key = " ".join(sorted(kb.tokens(question)))
        if key in st.cache:
            return st.cache[key]
        if st.tokens >= settings["token_budget"]:
            return None
        utts = self.db.utterances(sid)[-6:]
        ctx = "\n".join(f"{u['speaker'] or 'Speaker'}: {u['text']}" for u in utts)
        try:
            c = self.provider.complete(
                "You are a concise assistant inside a live meeting/study companion. Answer the question in at most 3 sentences. "
                "If you are not sure, say so explicitly. Do not invent sources.",
                f"Recent conversation:\n{ctx}\n\nQuestion: {question}")
        except ProviderError:
            st.provider_errors += 1
            return None
        st.tokens += c.tokens_in + c.tokens_out
        self.db.add_usage(sid, "answer", self.provider.name, True, c.tokens_in, c.tokens_out)
        # Safety verification: model-only answers have no evidence -> capped confidence, flagged unverified.
        ans = {"text": c.text, "confidence": 0.5, "evidence": [{"kind": "model_generated", "source": self.provider.name, "verified": False}],
               "origin": "llm"}
        st.cache[key] = ans
        return ans

    # ------------------------------------------------------------------ ingest
    def ingest(self, sid, text, speaker=None, ts_ms=None, user_speaking=False, source="typed") -> dict:
        t0 = time.perf_counter()
        s = self._session(sid)
        text = (text or "").strip()
        if not text:
            raise SessionError(422, "empty utterance")
        st = self._state(sid)
        if ts_ms is None:
            ts_ms = int((time.time() - s["started_at"]) * 1000)
        st.seq += 1
        utt = self.db.add_utterance(sid, st.seq, ts_ms, speaker, text, source)
        mode, cfg = s["mode"], {**P.DEFAULT_SETTINGS, **s["settings"]}

        docs = self.db.documents(sid)
        evs, new_facts = E.detect(text, facts=st.facts, documents=docs, profile=s["profile"])
        for k, v in new_facts.items():
            st.facts[k] = {**v, "utt_id": utt["id"], "ts_ms": ts_ms}

        out_ivs, out_evs = [], []
        for ev in evs:
            if ev.type == E.CONTRADICTION:  # attach readable timestamp of the earlier statement
                ev.meta["old"] = {**ev.meta["old"], "ts": fmt_ts(ev.meta["old"].get("ts_ms", 0))}
            answer = None
            if ev.type == E.QUESTION:
                answer = self._answer(sid, st, ev.text, cfg, allow_llm=(mode != "called_on" and not cfg["dnd"]))
            fp = self._fingerprint(ev)
            recent = [m for m in st.delivered_ms if ts_ms - m < 60000]
            ctx = P.PolicyContext(now_ms=ts_ms, last_delivered_ms=max(st.delivered_ms) if st.delivered_ms else None,
                                  delivered_count=len(st.delivered_ms), recent_delivered_60s=len(recent),
                                  seen_fingerprints=st.seen, user_speaking=user_speaking)
            has_ev = bool(ev.meta.get("evidence")) or bool(answer and answer["origin"] == "local_retrieval")
            conf = ev.confidence if ev.type != E.QUESTION or not answer else min(ev.confidence, answer["confidence"])
            dec = P.decide(ev.type, ev.meta, conf, fp, answer is not None, has_ev, mode, cfg, ctx)
            if dec.action != "drop":
                st.seen.add(fp)
            self.db.add_event(sid, utt["id"], ev.type, ev.confidence, {"meta": ev.meta, "fingerprint": fp, "decision": dec.to_dict()})
            out_evs.append({"type": ev.type, "confidence": ev.confidence, "decision": dec.to_dict()})

            if dec.action == "drop" or ev.type == E.FACTUAL_CLAIM or (ev.type == E.QUESTION and not answer):
                continue
            title, body, evidence = self._compose(ev, answer, cfg, mode, s["profile"])
            status = {"deliver": "delivered", "card": "pending", "passive": "passive"}[dec.action]
            iv = self.db.add_intervention(sid, utt["id"], ev.type, dec.priority, status, title, body, evidence, conf,
                                          dec.score, {**dec.to_dict(), "question_utt": utt["id"]}, "auto", ts_ms)
            if status == "delivered":
                st.delivered_ms.append(ts_ms)
            out_ivs.append(iv)
        proc = round((time.perf_counter() - t0) * 1000, 2)
        self.db.set_proc_ms(utt["id"], proc)
        return {"utterance": {**utt, "proc_ms": proc}, "events": out_evs, "interventions": out_ivs}

    @staticmethod
    def _fingerprint(ev) -> str:
        if ev.type == E.POSSIBLE_ERROR and ev.meta.get("rule"):
            return f"err:{ev.meta['rule']}"
        if ev.type == E.CONTRADICTION:
            return f"contra:{ev.meta['subject']}:{ev.meta['new']['value']}"
        return f"{ev.type}:{' '.join(sorted(kb.tokens(ev.text)))[:200]}"

    @staticmethod
    def _compose(ev, answer, cfg, mode, profile):
        m, L = ev.meta, cfg.get("lang", "en")
        if ev.type == E.POSSIBLE_ERROR:
            if m.get("verdict") == "confirmed_error":
                socratic = cfg.get("socratic")
                return (tr(L, "think") if socratic else tr(L, "misconception", topic=m["topic"]),
                        m["hint"] if socratic else m["correction"], m["evidence"])
            return tr(L, "verify"), m["correction"], m["evidence"]
        if ev.type == E.CONTRADICTION:
            o, n = m["old"], m["new"]
            return (tr(L, "contradiction"), tr(L, "contra_body", ts=o.get("ts", "?"), old=o["raw"], new=n["raw"], subj=m["subject"]),
                    [{"kind": "session_memory", "utterance_id": o.get("utt_id")}])
        if ev.type == E.QUESTION:
            return tr(L, "answer_sugg"), answer["text"], answer["evidence"]
        if ev.type == E.DECISION:
            return tr(L, "decision"), ev.text, []
        if ev.type == E.ACTION_ITEM:
            ns = tr(L, "not_stated")
            return tr(L, "action"), tr(L, "action_body", text=ev.text, owner=m.get("owner_stated") or ns, deadline=m.get("deadline_stated") or ns), []
        return ev.type, ev.text, []

    # ------------------------------------------------------------------ called-on
    def call(self, sid, text=None) -> dict:
        s = self._session(sid)
        st = self._state(sid)
        cfg = {**P.DEFAULT_SETTINGS, **s["settings"]}
        qutt = None
        if not text:
            qs = [e for e in self.db.events(sid) if e["type"] == E.QUESTION]
            if not qs:
                raise SessionError(422, "no question to answer yet; type or speak one")
            last = qs[-1]
            qutt = last["utterance_id"]
            text = next(u["text"] for u in self.db.utterances(sid) if u["id"] == qutt)
        ans = self._answer(sid, st, text, cfg, allow_llm=True)
        if ans:
            title, body, evidence, conf = tr(cfg.get("lang", "en"), "answer"), ans["text"], ans["evidence"], ans["confidence"]
        else:
            L = cfg.get("lang", "en")
            title, conf, evidence = tr(L, "no_answer"), 0.0, []
            body = tr(L, "no_answer_body")
        iv = self.db.add_intervention(sid, qutt, "USER_REQUEST", "important", "delivered", title, body, evidence, conf, 1.0,
                                      {"action": "deliver", "reasons": ["explicit_user_call"], "question_utt": qutt}, "called",
                                      int((time.time() - s["started_at"]) * 1000))
        pending = [i for i in self.db.interventions(sid) if i["status"] == "pending"]
        return {"intervention": iv, "pending_cards": len(pending), "provider_errors": st.provider_errors}

    # ------------------------------------------------------------------ feedback / summary / cost
    def act(self, iid, action=None, feedback=None):
        iv = self.db.get_intervention(iid)
        if not iv:
            raise SessionError(404, "intervention not found")
        status = {"approve": "approved", "dismiss": "dismissed", "save": "saved"}
        if action:
            if action not in status:
                raise SessionError(422, "action must be approve|dismiss|save")
            self.db.update_intervention(iid, status=status[action])
        if feedback:
            if feedback not in ("useful", "not_useful"):
                raise SessionError(422, "feedback must be useful|not_useful")
            self.db.update_intervention(iid, feedback=feedback)
        return self.db.get_intervention(iid)

    def summary(self, sid, persist=True) -> dict:
        s = self._session(sid, need_active=False)
        sm = build_summary(s, self.db.utterances(sid), self.db.events(sid), self.db.interventions(sid), s["settings"].get("lang", "en"))
        if persist:
            self.db.update_session(sid, summary=sm)
        return sm

    def cost(self, sid) -> dict:
        self._session(sid, need_active=False)
        rows = self.db.usage(sid)
        cloud_in = sum(r["tokens_in"] for r in rows if r["cloud"])
        cloud_out = sum(r["tokens_out"] for r in rows if r["cloud"])
        import os
        pi, po = os.environ.get("COMPANION_PRICE_IN_PER_MTOK"), os.environ.get("COMPANION_PRICE_OUT_PER_MTOK")
        est = None
        if pi and po:
            est = round(cloud_in / 1e6 * float(pi) + cloud_out / 1e6 * float(po), 6)
        utts = self.db.utterances(sid)
        return {"cloud_llm_calls": len([r for r in rows if r["cloud"]]), "tokens_in": cloud_in, "tokens_out": cloud_out,
                "estimated_cost_usd": est, "cost_note": "ESTIMATE from token counts and your configured prices; not a bill."
                if est is not None else "No prices configured (COMPANION_PRICE_*_PER_MTOK); showing tokens only.",
                "stt_cost_usd": 0.0, "stt_note": "STT runs in the browser (Web Speech API); the browser vendor may process audio in the cloud.",
                "local_events_processed": len(self.db.events(sid)), "utterances": len(utts),
                "processing": "local" if not cloud_in and not cloud_out else "local+cloud"}
