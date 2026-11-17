"""Seed two demo sessions (EN + KO) through the public API of a running server. Safe sample data only.
Usage: python3 scripts/seed_demo.py [http://127.0.0.1:8787]  -> prints session ids"""
import json, sys, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8787") + "/api"

def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or b"null")

DEMO = {
  "en": dict(title="Weekly product sync", doc=("plan.md", "The Q3 marketing budget is 50000 dollars. The launch date is March 3."), lines=[
    ("Alex", "What is the Q3 marketing budget?"),
    ("Alex", "I believe the budget is 50,000 dollars."),
    ("Dana", "Our agency quoted more. The budget is 80,000 dollars."),
    ("Alex", "We decided to go with vendor B."),
    ("Dana", "Dana will send the contract by Friday."),
    ("Sam", "Quick ML aside: random forest trains its trees sequentially, one after another."),
    ("Alex", "Can we also revisit the pricing page copy?")]),
  "ko": dict(title="주간 제품 회의", doc=("계획.md", "3분기 마케팅 예산은 5000만원입니다. 출시일은 3월 3일입니다."), lines=[
    ("민수", "3분기 마케팅 예산이 얼마인가요?"),
    ("민수", "제가 알기로 예산은 5000만원입니다."),
    ("지연", "대행사 견적은 더 높았어요. 예산은 8000만원입니다."),
    ("민수", "벤더 B로 가는 것으로 결정했습니다."),
    ("지연", "제가 금요일까지 계약서를 전달하겠습니다."),
    ("수현", "Random Forest는 모든 Decision Tree를 순차적으로 학습하는 거지?"),
    ("민수", "가격 페이지 문구도 다시 검토할 수 있을까요?")]),
}
out = {}
for lang, d in DEMO.items():
    call("POST", "/documents", {"name": d["doc"][0], "text": d["doc"][1]})
    s = call("POST", "/sessions", {"title": d["title"], "profile": "meeting", "mode": "interject",
        "consent": {"recording_consent_confirmed": True, "source": "seed_demo"}, "settings": {"lang": lang, "cooldown_sec": 5}})
    for i, (spk, text) in enumerate(d["lines"]):
        call("POST", f"/sessions/{s['id']}/utterances", {"text": text, "speaker": spk, "ts_ms": 12000 + i * 28000})
    call("POST", f"/sessions/{s['id']}/stop")
    out[lang] = s["id"]
print(json.dumps(out))
