"""Extractive session summary. Every item links back to an utterance id + timestamp.
Owners / deadlines are only reported when stated in the utterance; otherwise null (never guessed)."""
from __future__ import annotations

from collections import Counter

from . import knowledge as kb


def fmt_ts(ms: int) -> str:
    s = max(int(ms // 1000), 0)
    return f"{s // 60:02d}:{s % 60:02d}"


def build_summary(session: dict, utts: list[dict], events: list[dict], ivs: list[dict]) -> dict:
    by_id = {u["id"]: u for u in utts}

    def ref(e):
        u = by_id.get(e["utterance_id"], {})
        return {"utterance_id": e["utterance_id"], "ts": fmt_ts(u.get("ts_ms", 0)), "speaker": u.get("speaker"), "text": u.get("text", "")}

    answered = {iv["utterance_id"] for iv in ivs if iv["event_type"] == "QUESTION_DETECTED" and iv["status"] in ("delivered", "approved", "saved")}
    called_answered = {(iv["decision"] or {}).get("question_utt") for iv in ivs if iv["trigger"] == "called"}

    decisions = [ref(e) for e in events if e["type"] == "DECISION_MADE"]
    actions = []
    for e in events:
        if e["type"] == "ACTION_ITEM":
            m = (e["payload"] or {}).get("meta", {})
            actions.append({**ref(e), "owner": m.get("owner_stated"), "deadline": m.get("deadline_stated")})
    questions = [e for e in events if e["type"] == "QUESTION_DETECTED"]
    unresolved = [ref(e) for e in questions if e["utterance_id"] not in answered and e["utterance_id"] not in called_answered]
    contradictions = []
    for e in events:
        if e["type"] == "CONTRADICTION":
            meta = (e["payload"] or {}).get("meta", {})
            contradictions.append({**ref(e), "subject": meta.get("subject"), "earlier": (meta.get("old") or {}).get("raw"), "now": (meta.get("new") or {}).get("raw")})
    risks = []
    for e in events:
        if e["type"] == "POSSIBLE_ERROR":
            meta = (e["payload"] or {}).get("meta", {})
            risks.append({**ref(e), "verdict": meta.get("verdict"), "note": meta.get("correction")})
    evidence = [{"intervention_id": iv["id"], "evidence": iv["evidence"]} for iv in ivs if iv["evidence"]]

    topics = []
    chunk = 8
    for i in range(0, len(utts), chunk):
        part = utts[i:i + chunk]
        cnt = Counter(t for u in part for t in kb.tokens(u["text"]) if len(t) > 3 and t.isascii() or len(t) == 2 and not t.isascii())
        kw = [w for w, _ in cnt.most_common(4)]
        if kw:
            topics.append({"from": fmt_ts(part[0]["ts_ms"]), "to": fmt_ts(part[-1]["ts_ms"]), "keywords": kw, "utterance_ids": [u["id"] for u in part]})

    dur = (utts[-1]["ts_ms"] - utts[0]["ts_ms"]) if len(utts) > 1 else 0
    speakers = sorted({u["speaker"] for u in utts if u["speaker"]})
    exec_sum = (f"{len(utts)} utterances over {fmt_ts(dur)} from {len(speakers) or 1} labelled speaker(s). "
                f"{len(decisions)} decision(s), {len(actions)} action item(s), {len(unresolved)} unresolved question(s), "
                f"{len(contradictions)} contradiction(s), {len(risks)} possible error(s) flagged.") if utts else "No utterances recorded."

    follow = [f"Assign an owner/deadline: \"{a['text']}\"" for a in actions if not a["owner"] or not a["deadline"]]
    follow += [f"Resolve open question: \"{q['text']}\"" for q in unresolved]
    return {
        "generated_by": "local_extractive",
        "executive_summary": exec_sum, "topics": topics, "decisions": decisions, "action_items": actions,
        "unresolved_questions": unresolved, "contradictions": contradictions, "possible_errors": risks,
        "evidence": evidence, "follow_ups": follow,
    }


def to_markdown(session: dict, utts: list[dict], summary: dict, ivs: list[dict]) -> str:
    L = [f"# {session['title'] or 'Session'}", "",
         f"- Profile: {session['profile']} · Mode at end: {session['mode']} · Status: {session['status']}",
         f"- Audio recorded: {'yes' if session['record_audio'] else 'no'}", "",
         "## Executive summary", summary["executive_summary"], ""]
    def sec(title, items, fmt):
        L.append(f"## {title}")
        L.extend([fmt(i) for i in items] or ["_None_"])
        L.append("")
    sec("Key decisions", summary["decisions"], lambda d: f"- [{d['ts']}] {d['text']}")
    sec("Action items", summary["action_items"], lambda a: f"- [{a['ts']}] {a['text']} — owner: {a['owner'] or 'not stated'}, deadline: {a['deadline'] or 'not stated'}")
    sec("Unresolved questions", summary["unresolved_questions"], lambda q: f"- [{q['ts']}] {q['text']}")
    sec("Contradictions", summary["contradictions"], lambda c: f"- [{c['ts']}] {c['subject']}: earlier \"{c['earlier']}\", now \"{c['now']}\"")
    sec("Possible errors / risks", summary["possible_errors"], lambda r: f"- [{r['ts']}] ({r['verdict']}) {r['text']} → {r['note']}")
    sec("Follow-ups", summary["follow_ups"], lambda f: f"- {f}")
    sec("AI interventions", ivs, lambda i: f"- [{i['priority']}/{i['status']}] {i['title']}: {i['body']}")
    sec("Transcript", utts, lambda u: f"- [{fmt_ts(u['ts_ms'])}] **{u['speaker'] or 'Speaker'}**: {u['text']}")
    return "\n".join(L)
