# Product Spec (implemented subset)
Vision: AI that understands live context and helps at the right moment, within user-set permissions.
**Modes:** Hold (silent cards, user approves) · Called On (answers only when asked; Ctrl/⌘+K) · Interject (live delivery only if all gates pass; else downgrades to a card).
**Profiles:** meeting, learning (Socratic option), work (same engine; no work-specific features yet).
**Priorities:** Critical (confirmed error / strong contradiction) · Important (answerable question, needs-verification) · Suggestion · Passive (decisions/action items, recorded only).
## Phase 1 acceptance criteria
1. Session cannot start without explicit consent flag. 2. Transcript from browser STT or typed text. 3. Questions detected. 4. Answers only from evidence (docs) or an opt-in LLM, labelled unverified when model-only. 5. Hold cards with approve/save/dismiss/feedback. 6. Summary with timestamps; no invented owners/deadlines. 7. History + search. 8. Stop/export/delete (audio removed with session). All covered by `tests/test_core.py`.
Unimplemented spec items are listed in DEVELOPMENT_ROADMAP.md.
