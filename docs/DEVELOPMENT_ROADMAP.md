# Roadmap
- **Phase 0** partial: architecture, schema, API, privacy notes written. Competitor analysis, legal research, market/trademark check and cost modelling were **not** performed (no live research in this build).
- **Phase 1** done (see PRODUCT_SPEC acceptance criteria), except diarization, offline STT.
- **Phase 2** partial: Called On, Interject, policy engine, duplicate suppression, feedback, contradiction + doc-based checks done. Missing: web/citation verification, incremental LLM summaries, retrieval beyond keywords.
- **Phase 3** partial: Socratic mode, action items/decisions. Missing: persistent knowledge base across sessions, learning questions/reviews, personalization.
- **Phase 4** not started: Tauri shell (Python sidecar packaging is the main cost), tray, floating window, installer.
- **Phase 5** not started: calendar/doc/screen/browser connectors, tool execution with approval.
Next best steps: faster-whisper STT + VAD, diarization, WebSocket push, SQLCipher, larger independently-labelled eval set.
