import httpx
import pytest
from fastapi.testclient import TestClient

from app import events as E
from app import policy as P
from app.main import create_app
from app.providers import HTTPProvider, Provider, ProviderError, Completion

CONSENT = {"recording_consent_confirmed": True, "participants_notified": True}


# ------------------------------------------------------------------ helpers
@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(str(tmp_path), Provider()))


def start(c, mode="hold", profile="meeting", **kw):
    r = c.post("/api/sessions", json={"title": "t", "mode": mode, "profile": profile, "consent": CONSENT, **kw})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def say(c, sid, text, ts=0, **kw):
    r = c.post(f"/api/sessions/{sid}/utterances", json={"text": text, "ts_ms": ts, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def types(res):
    return [e["type"] for e in res["events"]]


# ------------------------------------------------------------------ event detection
@pytest.mark.parametrize("text,expected", [
    ("What is the budget for Q3?", True),
    ("how do we deploy this to production", True),
    ("다음 회의는 언제 하면 좋을까요?", True),
    ("배포는 누가 담당하나요", True),
    ("Who cares, why not ship it?", False),            # rhetorical
    ("This is great, right?", False),                   # tag question
    ("그거 맞죠?", False),                               # Korean tag question
    ("okay", False), ("네", False),
    ("The deadline is Friday.", False),
])
def test_question_detection(text, expected):
    assert E.is_question(text)[0] is expected


def test_misconception_ko_and_en():
    ev, _ = E.detect("Random Forest는 모든 Decision Tree를 순차적으로 학습하는 거지?", facts={}, documents=[], profile="learning")
    assert E.POSSIBLE_ERROR in [e.type for e in ev]
    assert E.QUESTION not in [e.type for e in ev]  # tag question is not an open question
    ev, _ = E.detect("A random forest trains its trees sequentially, one after another in sequence.", facts={}, documents=[], profile="learning")
    assert E.POSSIBLE_ERROR in [e.type for e in ev]


def test_correct_statement_not_flagged():
    for t in ["Gradient boosting trains trees sequentially.", "Random forest trains trees independently.",
              "Correlation does not imply causation."]:
        ev, _ = E.detect(t, facts={}, documents=[], profile="learning")
        assert E.POSSIBLE_ERROR not in [e.type for e in ev], t


def test_action_item_does_not_invent_owner_or_deadline():
    ev, _ = E.detect("We need to update the pricing page.", facts={}, documents=[], profile="meeting")
    a = [e for e in ev if e.type == E.ACTION_ITEM][0]
    assert a.meta["owner_stated"] is None and a.meta["deadline_stated"] is None
    ev, _ = E.detect("Dana will send the report by Friday.", facts={}, documents=[], profile="meeting")
    a = [e for e in ev if e.type == E.ACTION_ITEM][0]
    assert a.meta["owner_stated"] == "Dana" and a.meta["deadline_stated"].lower().endswith("friday")


# ------------------------------------------------------------------ policy
def decide(mode="interject", conf=0.9, etype="POSSIBLE_ERROR", meta=None, fp="x", ctx=None, **s):
    return P.decide(etype, meta or {"verdict": "confirmed_error"}, conf, fp, True, True, mode, s, ctx or P.PolicyContext())


def test_policy_modes():
    assert decide("interject").action == "deliver"
    assert decide("hold").action == "card"
    assert decide("called_on").action == "passive"
    assert decide("interject", dnd=True).action == "card"


def test_policy_gates_downgrade_not_drop():
    assert "user_is_speaking" in decide(ctx=P.PolicyContext(user_speaking=True)).reasons
    assert decide(ctx=P.PolicyContext(user_speaking=True)).action == "card"
    assert decide(conf=0.55, meta={"verdict": "needs_verification"}).action == "card"  # below confidence threshold
    assert decide(ctx=P.PolicyContext(delivered_count=10)).action == "card"
    # cooldown blocks non-critical but not critical
    ctx = P.PolicyContext(now_ms=5000, last_delivered_ms=1000)
    assert decide(etype="QUESTION_DETECTED", meta={}, conf=0.9, ctx=ctx).action == "card"
    assert decide(ctx=ctx).action == "deliver"


def test_policy_duplicate_and_passive():
    assert decide(ctx=P.PolicyContext(seen_fingerprints={"x"})).action == "drop"
    assert decide(etype="DECISION_MADE", meta={}, conf=0.9).action == "passive"


# ------------------------------------------------------------------ API: consent & lifecycle
def test_consent_required(client):
    assert client.post("/api/sessions", json={"title": "x"}).status_code == 400
    assert client.post("/api/sessions", json={"consent": {"recording_consent_confirmed": False}}).status_code == 400


def test_pause_resume_stop_flow(client):
    sid = start(client)
    client.post(f"/api/sessions/{sid}/pause")
    assert client.post(f"/api/sessions/{sid}/utterances", json={"text": "hello there everyone"}).status_code == 409
    client.post(f"/api/sessions/{sid}/resume")
    say(client, sid, "hello there everyone")
    assert client.post(f"/api/sessions/{sid}/stop").json()["status"] == "stopped"
    assert client.post(f"/api/sessions/{sid}/utterances", json={"text": "late words here"}).status_code == 409
    assert client.post(f"/api/sessions/{sid}/resume").status_code == 409


def test_empty_utterance_and_unknown_session(client):
    sid = start(client)
    assert client.post(f"/api/sessions/{sid}/utterances", json={"text": "   "}).status_code == 422
    assert client.post("/api/sessions/nope/utterances", json={"text": "hi"}).status_code == 404


# ------------------------------------------------------------------ end-to-end behaviours
def test_hold_mode_card_for_misconception_then_approve(client):
    sid = start(client, "hold", "learning")
    r = say(client, sid, "Random Forest는 모든 Decision Tree를 순차적으로 학습하는 거지?")
    assert len(r["interventions"]) == 1
    iv = r["interventions"][0]
    assert iv["status"] == "pending" and iv["priority"] == "critical" and "Gradient Boosting" in iv["body"]
    assert iv["evidence"][0]["kind"] == "curated_rule"
    assert client.post(f"/api/interventions/{iv['id']}/act", json={"action": "approve", "feedback": "useful"}).json()["status"] == "approved"


def test_interject_delivers_and_suppresses_duplicate(client):
    sid = start(client, "interject", "learning")
    a = say(client, sid, "Random forest trains its trees sequentially one after another.", ts=1000)
    assert a["interventions"][0]["status"] == "delivered"
    b = say(client, sid, "Random forest trains its trees sequentially one after another.", ts=3000)
    assert b["interventions"] == []
    assert b["events"][0]["decision"]["action"] == "drop"


def test_interject_not_while_user_speaking(client):
    sid = start(client, "interject", "learning")
    r = say(client, sid, "Random forest trains its trees sequentially one after another.", user_speaking=True)
    assert r["interventions"][0]["status"] == "pending"


def test_socratic_mode_gives_hint_not_answer(client):
    sid = start(client, "hold", "learning", settings={"socratic": True})
    iv = say(client, sid, "Gradient descent always reaches the global minimum.")["interventions"][0]
    assert "convex" not in iv["body"].lower() or "?" in iv["body"]
    assert iv["body"].endswith("?")


def test_contradiction_detected_and_revision_not(client):
    sid = start(client, "interject")
    say(client, sid, "The budget is 50,000 dollars.", ts=1000)
    r = say(client, sid, "The budget is 80,000 dollars.", ts=30000)
    assert "CONTRADICTION" in types(r)
    assert r["interventions"][0]["status"] == "delivered"
    r = say(client, sid, "Actually the budget is 90,000 dollars, I corrected it.", ts=60000)
    assert "CONTRADICTION" not in types(r)


def test_question_answered_from_user_document(client):
    sid = start(client, "hold")
    client.post("/api/documents", json={"name": "plan.md", "text": "The launch date is March 3. The Q3 budget is 50000 dollars for marketing."})
    r = say(client, sid, "What is the Q3 budget for marketing?")
    iv = r["interventions"][0]
    assert iv["event_type"] == "QUESTION_DETECTED" and "50000" in iv["body"]
    assert iv["evidence"][0]["source"] == "plan.md"


def test_numeric_claim_vs_document_is_needs_verification_only(client):
    sid = start(client, "interject")
    client.post("/api/documents", json={"name": "plan.md", "text": "The Q3 marketing budget is 50000 dollars."})
    r = say(client, sid, "The Q3 marketing budget is 90000 dollars.")
    iv = r["interventions"][0]
    assert "verify" in iv["title"].lower()
    assert iv["status"] == "pending"  # conf 0.55 < threshold -> never auto-interjects


def test_unanswerable_question_creates_no_noise_and_is_unresolved(client):
    sid = start(client, "interject")
    r = say(client, sid, "What is the capital of Atlantis?")
    assert r["interventions"] == [] and "QUESTION_DETECTED" in types(r)
    assert client.get(f"/api/sessions/{sid}/summary").json()["unresolved_questions"]


def test_called_on_mode(client):
    sid = start(client, "called_on")
    client.post("/api/documents", json={"name": "d.md", "text": "Deployment happens every Tuesday through the release pipeline."})
    r = say(client, sid, "When does deployment happen through the release pipeline?")
    assert [i["status"] for i in r["interventions"]] == ["passive"]  # silent: stored, not shown, until called
    c = client.post(f"/api/sessions/{sid}/call", json={}).json()
    assert c["intervention"]["status"] == "delivered" and "Tuesday" in c["intervention"]["body"]
    # explicit empty-context call
    sid2 = start(client, "called_on")
    assert client.post(f"/api/sessions/{sid2}/call", json={}).status_code == 422
    c = client.post(f"/api/sessions/{sid2}/call", json={"text": "What is zorblax?"}).json()
    assert c["intervention"]["title"] == "No answer available"


def test_summary_links_and_no_invented_owner(client):
    sid = start(client, "hold")
    say(client, sid, "We decided to go with vendor B.", ts=1000, speaker="A")
    say(client, sid, "We need to update the pricing page.", ts=5000, speaker="B")
    say(client, sid, "Dana will send the contract by Friday.", ts=9000, speaker="A")
    s = client.get(f"/api/sessions/{sid}/summary").json()
    assert s["decisions"][0]["utterance_id"] and s["decisions"][0]["ts"] == "00:01"
    owners = {a["text"]: a["owner"] for a in s["action_items"]}
    assert owners["We need to update the pricing page."] is None
    assert owners["Dana will send the contract by Friday."] == "Dana"
    assert any("Assign an owner" in f for f in s["follow_ups"])


def test_export_search_delete(client):
    sid = start(client, "hold")
    say(client, sid, "Zebra migration is scheduled for next quarter.")
    assert client.get(f"/api/sessions/{sid}/export?format=md").text.count("Zebra") >= 1
    assert client.get(f"/api/sessions/{sid}/export?format=json").json()["utterances"]
    assert client.get(f"/api/sessions/{sid}/export?format=pdf").status_code == 422
    assert len(client.get("/api/sessions?q=Zebra").json()) == 1
    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert client.get(f"/api/sessions/{sid}").status_code == 404
    assert client.get("/api/sessions?q=Zebra").json() == []


def test_audio_requires_opt_in_and_is_deleted(client, tmp_path):
    sid = start(client)
    assert client.post(f"/api/sessions/{sid}/audio", content=b"abc").status_code == 403
    sid = start(client, record_audio=True)
    assert client.post(f"/api/sessions/{sid}/audio", content=b"RIFFdata", headers={"content-type": "audio/webm"}).status_code == 201
    assert client.get(f"/api/sessions/{sid}/audio").content == b"RIFFdata"
    client.delete(f"/api/sessions/{sid}")
    assert not list((tmp_path / "audio").glob(f"{sid}.*"))


def test_long_session_state_survives_restart(tmp_path):
    c = TestClient(create_app(str(tmp_path), Provider()))
    sid = start(c, "interject")
    say(c, sid, "The budget is 50,000 dollars.", ts=0)
    for i in range(300):
        say(c, sid, f"Filler remark number {i} about nothing important here.", ts=1000 + i)
    c2 = TestClient(create_app(str(tmp_path), Provider()))  # fresh process: state rebuilt from DB
    assert "CONTRADICTION" in types(say(c2, sid, "The budget is 80,000 dollars.", ts=999999))
    m = c2.get(f"/api/sessions/{sid}/metrics").json()
    assert m["n"] == 302 and m["server_processing_ms_p95"] is not None


# ------------------------------------------------------------------ providers
def _mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_provider_openai_and_anthropic_parsing():
    def h(req):
        if req.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json={"choices": [{"message": {"content": " hi "}}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "yo"}], "usage": {"input_tokens": 7, "output_tokens": 3}})
    assert HTTPProvider("openai", "http://x/v1", "k", "m", _mock(h)).complete("s", "u") == Completion("hi", 5, 2)
    assert HTTPProvider("anthropic", "http://x", "k", "m", _mock(h)).complete("s", "u") == Completion("yo", 7, 3)


def test_llm_answer_cached_budgeted_and_marked_unverified(tmp_path):
    calls = []
    def h(req):
        calls.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Probably X."}}], "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    c = TestClient(create_app(str(tmp_path), HTTPProvider("openai", "http://x/v1", "k", "m", _mock(h))))
    sid = start(c, "hold")
    r = say(c, sid, "What is the airspeed velocity of a swallow?")
    iv = r["interventions"][0]
    assert iv["evidence"][0] == {"kind": "model_generated", "source": "openai:m", "verified": False} and iv["confidence"] <= 0.5
    say(c, sid, "What is the airspeed velocity of a swallow?")  # duplicate: no 2nd call
    assert len(calls) == 1
    cost = c.get(f"/api/sessions/{sid}/cost").json()
    assert cost["tokens_in"] == 100 and cost["processing"] == "local+cloud" and cost["estimated_cost_usd"] is None


def test_provider_failure_degrades_gracefully(tmp_path):
    c = TestClient(create_app(str(tmp_path), HTTPProvider("openai", "http://x/v1", "k", "m", _mock(lambda r: httpx.Response(500)))))
    sid = start(c, "interject")
    r = say(c, sid, "What is the airspeed velocity of a swallow?")
    assert r["interventions"] == []  # no crash, question still logged
    assert say(c, sid, "Random forest trains trees sequentially one after another.")["interventions"]  # rules still work


def test_token_budget_blocks_llm(tmp_path):
    n = []
    def h(req):
        n.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": "A"}}], "usage": {"prompt_tokens": 900, "completion_tokens": 200}})
    c = TestClient(create_app(str(tmp_path), HTTPProvider("openai", "http://x/v1", "k", "m", _mock(h))))
    sid = start(c, "hold", settings={"token_budget": 1000})
    say(c, sid, "What is the first thing we should check?")
    say(c, sid, "How should we handle the second distinct issue?")
    assert len(n) == 1


def test_cloud_requires_opt_in():
    from app.providers import provider_from_env
    with pytest.raises(SystemExit):
        provider_from_env({"COMPANION_PROVIDER": "openai", "COMPANION_API_KEY": "k", "COMPANION_MODEL": "m"})
    assert provider_from_env({}).available is False


def test_korean_session_composes_korean_text(client):
    sid = start(client, "hold", settings={"lang": "ko"})
    client.post("/api/documents", json={"name": "계획.md", "text": "3분기 마케팅 예산은 5000만원입니다."})
    iv = say(client, sid, "3분기 마케팅 예산이 얼마인가요?")["interventions"][0]
    assert iv["title"] == "답변 제안" and "5000만원" in iv["body"]
    say(client, sid, "예산은 5000만원입니다.", ts=1000)
    c = say(client, sid, "예산은 8000만원입니다.", ts=40000)["interventions"][0]
    assert c["title"] == "모순 가능성" and '"5000만원"' in c["body"]
    assert "발화" in client.get(f"/api/sessions/{sid}/summary").json()["executive_summary"]
