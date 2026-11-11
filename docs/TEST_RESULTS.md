# Test Results (run on macOS, Python 3.11, 2026-11-12)
- `pytest`: **37 passed, 0 failed** — event detection (EN/KO, rhetorical, tag), policy gates, consent/lifecycle, Hold/Called On/Interject flows, duplicate suppression, user-speaking, Socratic, contradiction vs revision, document answers, summary honesty, export/search/delete, audio opt-in & deletion, restart state rebuild (300 utterances), provider parsing (mocked), caching, token budget, provider failure, cloud opt-in.
- Eval (`docs/eval_output.json`): question P 0.92 / R 1.0; error P/R 1.0 (circular, see EVALUATION.md); 1 known misclassification.
- Manual UI smoke in the in-app browser: consent dialog, typed utterances, cards (critical/important/passive), stop → Notes, Cost, History rendered; no console errors.
- **Not tested:** real microphone/Web Speech STT, MediaRecorder audio, speechSynthesis, live cloud LLM calls, Windows, Safari/Firefox, accessibility audit, load.
- Earlier failures found and fixed during development: action-item owner detection, digit-in-token ("Q3") doc check, tag-question over-match for "okay?".
