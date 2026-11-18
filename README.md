# Hushcue

**Listens live. Speaks up when it matters.**

**English** | [한국어](README.ko.md)

## What is Hushcue?
Hushcue is a live AI companion for **meetings, study and work**. You switch it on for a session and it listens (only after you consent). While people talk, it quietly watches for things worth flagging:

- a **wrong claim** (e.g. "Random Forest trains its trees one after another"),
- a number that **contradicts** what was said earlier ("budget is 50M" → "budget is 80M"),
- a **question** nobody answered,
- a **decision** or an **action item** that was just made (with owner and deadline only if someone actually said them).

Then it decides **how loudly** to tell you. You choose the mode:

| Mode | Behaviour | Good for |
|---|---|---|
| **Hold** (default) | Never interrupts. Saves quiet cards that you approve, save or dismiss. | Meetings, lectures |
| **Called On** | Answers only when you ask it. | Focused work |
| **Interject** | Speaks up live, but only if every policy gate passes (importance, confidence, cooldown, max interruptions, do-not-disturb, not while you are talking). A blocked interjection becomes a card instead. | When a mistake would be costly |

Every decision is logged, so you can see *why* Hushcue spoke or stayed quiet. At the end you get notes with decisions, action items and open questions, each linked to a timestamp.

**Privacy by default:** data stays in a local SQLite file; nothing goes to an LLM unless you configure a provider; sessions need explicit consent; you can delete a session at any time.

*Name: a web search found no product with the exact name "Hushcue"; formal trademark clearance has not been done.*


![Live suggestions (English UI)](docs/img/en-feed.png)
![Session notes (English UI)](docs/img/en-notes.png)

*Screenshots use safe, made-up demo data (`scripts/seed_demo.py`), not real conversations.*

**Status: Phase 1 vertical slice + parts of Phase 2.** See [docs/DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) for exactly what is and isn't built.

## Run
```bash
pip install -r requirements.txt
./run.sh                 # http://127.0.0.1:8787  (override with PORT=)
python3 -m pytest -q     # 38 tests
python3 eval/run_eval.py # small hand-labelled eval
```
No API key needed: rules + retrieval over your own documents work offline. Speech-to-text uses the **browser's Web Speech API** (Chrome/Safari; may be cloud-processed by the browser vendor) or typed input. Optional LLM: see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## What works (verified — see docs/TEST_RESULTS.md)
Consent-gated session start · pause/resume/stop · live transcript (browser STT or typed) · question detection (EN/KO, ignores rhetorical/tag questions) · curated misconception detection (5 rules, demo KB) · numeric contradiction detection · numeric claims vs your documents ("needs verification", never "confirmed") · Hold / Called On / Interject with policy engine (threshold, cooldown, max interruptions, DND, duplicate suppression, no interjection while user speaks) · Socratic mode · decisions/action items (owner/deadline only if stated) · extractive summary linked to timestamps · SQLite history, search, Markdown/JSON export, delete · optional audio save · cost/latency panel.

## What does NOT work yet
Speaker diarization · server-side/offline STT (faster-whisper) · system-audio / Zoom / Meet / Teams capture · Tauri desktop shell, tray, installer · web search / RAG beyond keyword overlap · LLM summaries · PDF export · at-rest encryption · wake word · connectors · MISSING_INFORMATION / LEARNING_OPPORTUNITY / FOLLOW_UP events. Cloud LLM providers are implemented but **untested against a live API**.

UI languages: English and Korean (header toggle `EN / 한`; `?lang=ko`). Companion-generated text follows the session language; the Markdown export headings are still English.

Layout: `app/` (events, policy, engine, providers, storage, API) · `static/index.html` UI · `tests/` · `eval/` · `docs/`.
