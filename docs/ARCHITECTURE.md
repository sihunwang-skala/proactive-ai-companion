# Architecture
```
Browser: mic -> Web Speech API (STT) / typed text -> POST /utterances
Server:  events.detect (rules) -> engine (memory, retrieval, optional LLM) -> policy.decide -> storage (SQLite) -> response
         parallel: summary.build_summary (extractive, on demand / on stop)
```
- **events.py** low-cost detectors (questions, misconceptions, numeric contradictions, doc mismatch, decisions, action items). No LLM.
- **policy.py** pure function: score = conf·(0.30·relevance + 0.25·benefit + 0.30·urgency + 0.15·novelty) − 0.3·interruption_cost; mode/gates decide deliver | card | passive | drop. Every decision (incl. drops) is stored in `events.payload.decision` for audit/eval.
- **engine.py** per-session state (rebuilt from DB after restart), retrieval-first answering, LLM gated by mode, DND, token budget, cache; provider errors degrade to rules-only.
- **providers.py** `Provider` interface; `HTTPProvider` for OpenAI-compatible and Anthropic endpoints; default is none.
- **storage.py** SQLite, cascade delete. **main.py** FastAPI REST. **static/index.html** UI.
Context management: recent window (last 6 utterances) + user documents + retrieved passages are sent to an LLM only when gated in; the rolling LLM summary and long-term memory are not implemented.
Platform limits (general knowledge — verify before relying): browser getUserMedia captures the microphone only. Capturing system/meeting audio on macOS needs ScreenCaptureKit or a virtual audio driver plus separate permissions; Zoom/Meet/Teams bots need their official SDKs/APIs and ToS review. **None of this is implemented or claimed.**
