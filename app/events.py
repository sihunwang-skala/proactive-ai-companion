"""Low-cost, rule-based event detection (no LLM). Each detector is independent and testable."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import knowledge as kb

QUESTION = "QUESTION_DETECTED"
FACTUAL_CLAIM = "FACTUAL_CLAIM_DETECTED"
POSSIBLE_ERROR = "POSSIBLE_ERROR"
CONTRADICTION = "CONTRADICTION"
DECISION = "DECISION_MADE"
ACTION_ITEM = "ACTION_ITEM"
USER_REQUEST = "USER_REQUEST"
# Declared in the spec but not implemented in this MVP detector set:
NOT_IMPLEMENTED = ["MISSING_INFORMATION", "LEARNING_OPPORTUNITY", "FOLLOW_UP_REQUIRED"]


@dataclass
class Event:
    type: str
    confidence: float
    text: str
    meta: dict = field(default_factory=dict)


_WH = re.compile(r"^(what|why|how|when|where|who|whom|which|whose|is|are|was|were|do|does|did|can|could|should|would|will|shall|has|have|had)\b", re.I)
_KO_Q_END = re.compile(r"(까요|나요|인가요|ㄴ가요|을까요|ㄹ까요|습니까|니까|할까|일까|뭐예요|뭔가요|어때요|어떻게 되나요)\s*[?]?$")
_TAG_Q = re.compile(r"(,?\s*(right|correct|isn't it|aren't they|doesn't it|don't you think)\s*\?$)|(,\s*(no|yeah|okay)\s*\?$)|((맞죠|맞지|그렇죠|그렇지|거지|거죠|아닌가요|아니야|맞아)\s*\?$)", re.I)
_RHETORICAL = re.compile(r"\b(why not|who cares|who knows|how hard can it be|what could go wrong|isn't that obvious)\b|누가 알겠|뭐 어때|어쩌겠어|아니겠어", re.I)
_SMALLTALK = re.compile(r"^(hi|hello|hey|thanks|thank you|ok|okay|yes|no|yeah|uh|um|hmm|good morning|네|아니요|음|어|안녕하세요|감사합니다|좋아요)[.!? ]*$", re.I)
_DECISION = re.compile(r"\b(we('ve| have)? decided|we agreed|let'?s go with|the decision is|we('ll| will) go with|approved)\b|결정했|하기로 (했|결정|합의)|으로 가겠습니다|로 가죠|합의했", re.I)
_ACTION = re.compile(r"\b(i('ll| will)|i can|we need to|needs? to|action item|todo|to-do|please (send|prepare|review|update|share))\b|제가 .{0,25}(하겠|할게|맡)|\S+(님|씨)?(이|가)? .{0,25}(해주세요|해 주세요|부탁)|하겠습니다|할게요|담당", re.I)
_DEADLINE = re.compile(r"\b(by|before|until|due)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|next week|end of (the )?(day|week|month)|\d{1,2}/\d{1,2}|\w+ \d{1,2})|(오늘|내일|모레|이번 주|다음 주|월요일|화요일|수요일|목요일|금요일|\d{1,2}월 \d{1,2}일)\s*까지", re.I)
_OWNER_EN = re.compile(r"^(?P<owner>[A-Z][a-z]+) (will|can|needs to|is going to) ")
_OWNER_KO = re.compile(r"^(?P<owner>[가-힣]{2,4})(님|씨)?(이|가|은|는)\s")
_NOT_NAMES = {"We", "They", "It", "This", "That", "He", "She", "You", "There", "Everyone", "Someone"}
_CLAIM_HINT = re.compile(r"\b(is|are|always|never|only|means|causes?|requires?|equals?)\b|은|는|이다|입니다|거야|이에요|항상|절대", re.I)


def is_question(text: str) -> tuple[bool, float, str]:
    """Return (is_question, confidence, kind). kind in {'direct','rhetorical','tag','none'}."""
    t = text.strip()
    if not t or _SMALLTALK.match(t):
        return False, 0.0, "none"
    if _RHETORICAL.search(t):
        return False, 0.0, "rhetorical"
    if _TAG_Q.search(t):
        return False, 0.0, "tag"
    if t.endswith("?") or t.endswith("？"):
        return True, 0.9, "direct"
    if _WH.match(t) and len(t.split()) >= 4:
        return True, 0.7, "direct"  # STT often drops punctuation
    if _KO_Q_END.search(t):
        return True, 0.75, "direct"
    return False, 0.0, "none"


def detect(text: str, *, facts: dict, documents: list[dict], profile: str, is_revision_ok: bool = True) -> tuple[list[Event], dict]:
    """Detect events for one final utterance.

    `facts` is the session's numeric-fact memory {(subj, unit): {"value", "utt_id", "ts_ms", "raw"}}; it is
    read here and the *new* facts to store are returned in the second element (caller commits them).
    """
    ev: list[Event] = []
    t = text.strip()
    if not t:
        return ev, {}

    q, qconf, kind = is_question(t)
    if q:
        ev.append(Event(QUESTION, qconf, t, {"kind": kind}))

    # curated misconceptions (applies to statements and tag-questions alike)
    lang = "ko" if kb.has_hangul(t) else "en"
    rule_hit = False
    for r in kb.match_rules(t):
        rule_hit = True
        ev.append(Event(POSSIBLE_ERROR, r["confidence"], t, {
            "verdict": "confirmed_error", "rule": r["id"], "topic": r["topic"], "lang": lang,
            "correction": r["correction"][lang], "hint": r["hint"][lang], "evidence": [{"source": r["source"], "kind": "curated_rule"}],
        }))

    new_facts: dict = {}
    contradicted = False
    for f in kb.extract_numeric_facts(t):
        key = (f["subj"], f["unit"])
        prev = facts.get(key)
        revision = bool(kb.REVISION_RE.search(t))
        if prev and prev["value"] != f["value"] and not revision:
            ev.append(Event(CONTRADICTION, 0.8, t, {
                "subject": f["subj"], "unit": f["unit"], "old": prev, "new": {"value": f["value"], "raw": f["raw"]},
            }))
            contradicted = True
        new_facts[key] = {"value": f["value"], "raw": f["raw"]}

    # numeric claim vs user documents -> needs verification (never "confirmed")
    if new_facts and not contradicted and not rule_hit and documents:
        ev.extend(_check_against_documents(t, documents))

    if (_CLAIM_HINT.search(t) or new_facts) and not q and not any(e.type in (POSSIBLE_ERROR, CONTRADICTION) for e in ev):
        if len(t.split()) >= 4 or kb.has_hangul(t):
            ev.append(Event(FACTUAL_CLAIM, 0.5, t, {}))

    if _DECISION.search(t):
        ev.append(Event(DECISION, 0.75, t, {}))

    m = _OWNER_EN.match(t)
    if m and m.group("owner") in _NOT_NAMES:
        m = None
    if (_ACTION.search(t) or m) and not q:
        owner = None
        m = m or _OWNER_KO.match(t)
        if m:
            owner = m.group("owner")
        dl = _DEADLINE.search(t)
        ev.append(Event(ACTION_ITEM, 0.7, t, {"owner_stated": owner, "deadline_stated": dl.group(0) if dl else None}))
    return ev, new_facts


def _check_against_documents(text: str, documents: list[dict]) -> list[Event]:
    claim_nums = kb.numbers_in(text)
    q = kb.tokens(re.sub(r"\d[\d,\.]*", " ", text))
    out = []
    for h in kb.retrieve(re.sub(r"\d[\d,\.]*", " ", text), documents, k=1, min_shared=2, min_ratio=0.5):
        doc_nums = kb.numbers_in(h["passage"])
        if doc_nums and claim_nums and not (claim_nums & doc_nums):
            out.append(Event(POSSIBLE_ERROR, 0.55, text, {
                "verdict": "needs_verification",
                "correction": f"Your document \"{h['doc']}\" says: \"{h['passage']}\" — the figure mentioned differs. Please verify.",
                "evidence": [{"source": h["doc"], "kind": "user_document", "quote": h["passage"]}],
            }))
    return out
