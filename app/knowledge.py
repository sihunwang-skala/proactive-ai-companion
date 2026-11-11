"""Curated misconception rules + lightweight local retrieval.

The rule base is a small DEMO knowledge base (not exhaustive). Anything outside it is
only checked against user-provided documents, or by an opt-in LLM provider.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------- misconception rules
RULES = [
    {
        "id": "rf-sequential",
        "topic": "Machine Learning",
        "patterns": [r"(random\s*forest|랜덤\s*포레스트).{0,60}(sequential|one after another|in sequence|순차)"],
        "correction": {
            "en": "Trees in a Random Forest are normally trained independently (bagging + random feature subsets). "
                  "Sequential training, where each tree corrects the previous one, is characteristic of Gradient Boosting.",
            "ko": "Random Forest의 트리들은 일반적으로 서로 독립적으로 학습됩니다(배깅 + 무작위 특성 선택). "
                  "이전 트리의 오차를 보완하며 순차적으로 학습하는 것은 Gradient Boosting의 특징입니다.",
        },
        "hint": {
            "en": "Does each tree in a Random Forest depend on the previous tree's errors? Compare with Gradient Boosting.",
            "ko": "Random Forest의 각 트리가 이전 트리의 오차에 의존할까요? Gradient Boosting과 비교해 보세요.",
        },
        "source": "Breiman (2001) Random Forests; Friedman (2001) Greedy Function Approximation",
        "confidence": 0.9,
    },
    {
        "id": "pvalue-null-prob",
        "topic": "Statistics",
        "patterns": [
            r"(p-?value|p\s*값).{0,60}probability\s+(that\s+)?the\s+null.{0,25}(true|correct)",
            r"(p-?value|p\s*값|p값).{0,60}귀무\s*가설.{0,12}(참|맞)\w*\s*확률",
        ],
        "correction": {
            "en": "A p-value is the probability of data at least this extreme assuming the null hypothesis is true; "
                  "it is not the probability that the null hypothesis is true.",
            "ko": "p-값은 귀무가설이 참이라고 가정할 때 관측 결과만큼 극단적인 결과가 나올 확률이며, "
                  "귀무가설이 참일 확률이 아닙니다.",
        },
        "hint": {
            "en": "What is the p-value conditioned on: the data, or the null hypothesis being true?",
            "ko": "p-값은 무엇을 조건으로 하는 확률일까요? 데이터일까요, 귀무가설이 참이라는 가정일까요?",
        },
        "source": "Wasserstein & Lazar (2016), ASA Statement on p-values",
        "confidence": 0.9,
    },
    {
        "id": "corr-causation",
        "topic": "Statistics",
        "patterns": [
            r"correlation\s+(implies|proves|means|equals)\s+causation",
            r"상관(관계)?(가|이)?\s*(있으면|높으면).{0,15}인과(관계)?(가|도)?\s*(있|성립)",
        ],
        "correction": {
            "en": "Correlation alone does not establish causation; confounders or reverse causality can produce correlation.",
            "ko": "상관관계만으로는 인과관계가 성립하지 않습니다. 교란 변수나 역인과가 상관을 만들 수 있습니다.",
        },
        "hint": {
            "en": "Can you think of a third variable that could drive both quantities?",
            "ko": "두 변수를 동시에 움직이는 제3의 변수가 있을 수 있을까요?",
        },
        "source": "Standard statistics textbooks (e.g. Pearl, Causality)",
        "confidence": 0.85,
    },
    {
        "id": "gd-global",
        "topic": "Machine Learning",
        "patterns": [
            r"gradient\s*descent.{0,40}always.{0,30}global",
            r"경사\s*하강(법)?.{0,30}항상.{0,20}(전역|글로벌|global)",
        ],
        "correction": {
            "en": "Gradient descent is only guaranteed to reach the global minimum for convex objectives; "
                  "for non-convex losses it can stop at local minima or saddle points.",
            "ko": "경사하강법이 전역 최솟값에 도달한다는 보장은 볼록(convex) 목적함수에서만 성립합니다. "
                  "비볼록 손실에서는 지역 최솟값이나 안장점에서 멈출 수 있습니다.",
        },
        "hint": {
            "en": "Under what property of the loss function is the global minimum guaranteed?",
            "ko": "손실함수가 어떤 성질을 가질 때 전역 최솟값이 보장될까요?",
        },
        "source": "Boyd & Vandenberghe, Convex Optimization",
        "confidence": 0.85,
    },
    {
        "id": "overfit-low-train",
        "topic": "Machine Learning",
        "patterns": [
            r"overfit\w*.{0,40}(low|poor)\s+(training|train)\s+(accuracy|performance|error)",
            r"과적합.{0,20}(훈련|학습).{0,10}(정확도|성능).{0,6}(낮|떨어)",
        ],
        "correction": {
            "en": "Overfitting typically shows as HIGH training performance with noticeably worse validation/test performance.",
            "ko": "과적합은 보통 훈련 성능은 높은데 검증/테스트 성능이 눈에 띄게 낮은 현상으로 나타납니다.",
        },
        "hint": {
            "en": "Which of training or validation performance drops when a model overfits?",
            "ko": "모델이 과적합되면 훈련 성능과 검증 성능 중 어느 쪽이 떨어질까요?",
        },
        "source": "Hastie, Tibshirani & Friedman, The Elements of Statistical Learning",
        "confidence": 0.8,
    },
]
_COMPILED = [(r, [re.compile(p, re.I) for p in r["patterns"]]) for r in RULES]


def match_rules(text: str) -> list[dict]:
    return [r for r, pats in _COMPILED if any(p.search(text) for p in pats)]


# ---------------------------------------------------------------- retrieval
STOP = set(
    "a an the is are was were be to of and or in on for with that this it as at by from do does did what which who "
    "how why when where can could should would will we you i they he she not no yes so if then than about into our "
    "your their my me us have has had".split()
)


def has_hangul(s: str) -> bool:
    return bool(re.search(r"[가-힣]", s))


def tokens(s: str) -> set[str]:
    s = s.lower()
    out = {w for w in re.findall(r"[a-z][a-z0-9\-]+", s) if w not in STOP and len(w) > 1}
    for w in re.findall(r"[가-힣]+", s):
        if len(w) == 1:
            out.add(w)
        out.update(w[i:i + 2] for i in range(len(w) - 1))
    return out


def split_passages(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) > 8]


def retrieve(query: str, documents: list[dict], k: int = 3, min_shared: int = 2, min_ratio: float = 0.4) -> list[dict]:
    q = tokens(query)
    if not q:
        return []
    hits = []
    for d in documents:
        for p in split_passages(d["text"]):
            shared = q & tokens(p)
            ratio = len(shared) / len(q)
            if len(shared) >= min_shared and ratio >= min_ratio:
                hits.append({"doc_id": d["id"], "doc": d["name"], "passage": p, "score": round(ratio, 3)})
    hits.sort(key=lambda h: -h["score"])
    return hits[:k]


# ---------------------------------------------------------------- numeric facts
_NUM = r"(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)"
_UNIT = r"(?P<unit>%|percent|퍼센트|million|k|m|만\s*원|원|달러|dollars?|days?|weeks?|months?|일|주|개월|명|people|users?)?"
FACT_RE = re.compile(
    r"(?P<subj>[A-Za-z가-힣][A-Za-z가-힣 ]{1,40}?)\s*(?:is|are|will be|was|=|은|는|이|가)\s*"
    r"(?:about |around |approximately |roughly |약 )?" + _NUM + r"\s*" + _UNIT,
    re.I,
)
REVISION_RE = re.compile(r"\b(actually|correction|sorry|i meant|to correct|updated?)\b|수정|정정|아니,|아니라", re.I)
_UNIT_NORM = {"percent": "%", "퍼센트": "%", "dollar": "$", "dollars": "$", "달러": "$", "users": "user", "people": "user"}


def extract_numeric_facts(text: str) -> list[dict]:
    facts = []
    for m in FACT_RE.finditer(text):
        subj = m.group("subj").strip().lower().split()[-1]
        if subj in STOP:
            continue
        unit = (m.group("unit") or "").lower().replace(" ", "")
        unit = _UNIT_NORM.get(unit, unit)
        facts.append({"subj": subj, "unit": unit, "value": float(m.group("num").replace(",", "")), "raw": m.group(0).strip()})
    return facts


def numbers_in(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in re.findall(r"(?<![A-Za-z\d.])(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)", text)}
