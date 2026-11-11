"""Offline evaluation of rule-based detection + policy on a hand-labelled set.
Labels were written by the developer (author bias; small n) -> indicative only, NOT a benchmark.
Latency = detector+policy compute on this machine, excluding STT/network. Run: python eval/run_eval.py"""
import json, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from app import events as E
from app.main import create_app
from app.providers import Provider
import tempfile

rows = [json.loads(l) for l in open(Path(__file__).parent / "dataset.jsonl", encoding="utf-8")]
def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0; r = tp / (tp + fn) if tp + fn else 0.0
    return round(p, 3), round(r, 3), round(2 * p * r / (p + r), 3) if p + r else 0.0
qtp = qfp = qfn = etp = efp = efn = 0; etn = 0; lat = []; misses = []
for r in rows:
    t0 = time.perf_counter()
    ev, _ = E.detect(r["text"], facts={}, documents=[], profile="learning")
    lat.append((time.perf_counter() - t0) * 1000)
    q = any(e.type == E.QUESTION for e in ev); er = any(e.type == E.POSSIBLE_ERROR for e in ev)
    qtp += q and r["label_question"]; qfp += q and not r["label_question"]; qfn += (not q) and r["label_question"]
    etp += er and r["label_error"]; efp += er and not r["label_error"]; efn += (not er) and r["label_error"]; etn += (not er) and not r["label_error"]
    if q != r["label_question"] or er != r["label_error"]: misses.append((r["scenario"], r["text"], f"q={q}", f"err={er}"))
# interject-mode session over the whole set: count interruptions on non-error items
tmp = tempfile.mkdtemp(); c = TestClient(create_app(tmp, Provider()))
sid = c.post("/api/sessions", json={"mode": "interject", "profile": "learning", "consent": {"recording_consent_confirmed": True}, "settings": {"max_interruptions": 999, "cooldown_sec": 0}}).json()["id"]
bad = good = 0
for i, r in enumerate(rows):
    out = c.post(f"/api/sessions/{sid}/utterances", json={"text": r["text"], "ts_ms": i * 5000}).json()
    for iv in out["interventions"]:
        if iv["status"] == "delivered":
            if r["label_error"]: good += 1
            else: bad += 1
lat.sort()
print(json.dumps({
  "n": len(rows),
  "question_detection": dict(zip(("precision", "recall", "f1"), prf(qtp, qfp, qfn))),
  "error_detection": {**dict(zip(("precision", "recall", "f1"), prf(etp, efp, efn))), "false_positive_rate": round(efp / (efp + etn), 3) if efp + etn else 0.0},
  "interject_mode": {"delivered_on_true_errors": good, "unnecessary_interruptions": bad, "unnecessary_interruption_rate": round(bad / max(bad + good, 1), 3)},
  "detector_latency_ms": {"p50": round(statistics.median(lat), 3), "p95": round(lat[int(len(lat) * .95) - 1], 3)},
  "misclassified": misses}, ensure_ascii=False, indent=1))
