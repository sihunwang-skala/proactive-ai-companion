# Decisions
1. **Python/FastAPI + static HTML/vanilla JS**, not Tauri/React yet: fewest moving parts to get a verifiable vertical slice; Tauri + Python sidecar packaging deferred to Phase 4.
2. **Browser Web Speech API for STT**: zero install/cost, but cloud-processed by vendor and Chrome/Safari only; replaced later by faster-whisper behind the same /utterances contract.
3. **Rules first, LLM gated**: cheap, deterministic, testable; LLM only when evidence is missing.
4. **Policy as a pure function** with logged decisions for offline evaluation.
5. **Gates downgrade, never silently drop** (except duplicates): blocked interjections become cards.
6. **Honesty over coverage**: no evidence → no answer; "needs verification" ≠ "confirmed error"; owners/deadlines never inferred.
7. No LangGraph, no vector DB, no WebSocket: not justified by current requirements.
8. Repo split (public portfolio vs private core) is a publishing decision for the owner; this repo is one tree, nothing pushed.
