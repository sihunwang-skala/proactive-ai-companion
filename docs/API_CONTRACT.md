# API (localhost REST; errors are `{"detail": ...}`)
POST /api/sessions {title,profile,mode,record_audio,consent:{recording_consent_confirmed:true},settings} → 201 (400 without consent) · GET /api/sessions?q= · GET /api/sessions/{id}
POST /api/sessions/{id}/utterances {text,speaker,ts_ms,user_speaking,source} → {utterance,events,interventions} (409 if not active, 422 empty)
POST /api/sessions/{id}/call {text?} · PATCH /api/sessions/{id}/settings {mode?,settings?} · POST …/pause|resume|stop
POST /api/interventions/{id}/act {action:approve|dismiss|save, feedback:useful|not_useful}
GET …/summary | cost | metrics | export?format=md|json | audio · POST …/audio (raw body; only if record_audio) · DELETE /api/sessions/{id} → 204
POST/GET /api/documents · GET /api/health. No WebSocket yet (UI uses request/response).
