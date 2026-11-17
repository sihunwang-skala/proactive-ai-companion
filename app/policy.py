"""Intervention policy engine: pure function, fully logged, easy to evaluate offline."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

DEFAULT_SETTINGS = {
    "interject_threshold": 0.60,   # min score for live interjection
    "confidence_threshold": 0.60,  # min detector confidence for live interjection
    "card_threshold": 0.30,        # min score to surface a silent card
    "cooldown_sec": 20,
    "max_interruptions": 10,
    "dnd": False,
    "voice": False,
    "socratic": False,
    "token_budget": 20000,
    "lang": "en",
}

PRIORITIES = ("critical", "important", "suggestion", "passive")
_URGENCY = {"critical": 1.0, "important": 0.7, "suggestion": 0.4, "passive": 0.1}


@dataclass
class PolicyContext:
    now_ms: int = 0
    last_delivered_ms: int | None = None
    delivered_count: int = 0
    recent_delivered_60s: int = 0
    seen_fingerprints: set = field(default_factory=set)
    user_speaking: bool = False


@dataclass
class Decision:
    action: str            # deliver | card | passive | drop
    priority: str
    score: float
    reasons: list
    components: dict

    def to_dict(self):
        return asdict(self)


def priority_for(event_type: str, meta: dict, confidence: float, answerable: bool) -> str:
    if event_type == "POSSIBLE_ERROR":
        return "critical" if meta.get("verdict") == "confirmed_error" else "important"
    if event_type == "CONTRADICTION":
        return "critical" if confidence >= 0.85 else "important"
    if event_type == "QUESTION_DETECTED":
        return "important" if answerable else "passive"
    if event_type in ("DECISION_MADE", "ACTION_ITEM", "FACTUAL_CLAIM_DETECTED"):
        return "passive"
    return "suggestion"


def decide(event_type: str, meta: dict, confidence: float, fingerprint: str, answerable: bool,
           has_evidence: bool, mode: str, settings: dict, ctx: PolicyContext) -> Decision:
    s = {**DEFAULT_SETTINGS, **settings}
    priority = priority_for(event_type, meta, confidence, answerable)
    reasons: list[str] = []

    relevance = 1.0 if (answerable or event_type in ("POSSIBLE_ERROR", "CONTRADICTION")) else 0.3
    urgency = _URGENCY[priority]
    benefit = confidence * (1.0 if has_evidence else 0.7)
    novelty = 0.0 if fingerprint in ctx.seen_fingerprints else 1.0
    cost = (0.25 if ctx.user_speaking else 0.10) + 0.15 * min(ctx.recent_delivered_60s, 3)
    score = confidence * (0.30 * relevance + 0.30 * urgency + 0.25 * benefit + 0.15 * novelty) - 0.30 * cost
    score = round(max(score, 0.0), 3)
    comp = dict(relevance=relevance, urgency=urgency, benefit=round(benefit, 3), novelty=novelty,
                interruption_cost=round(cost, 3), confidence=confidence)

    def out(action, why):
        reasons.append(why)
        return Decision(action, priority, score, reasons, comp)

    if novelty == 0.0:
        return out("drop", "duplicate_suppressed")
    if priority == "passive":
        return out("passive", "recorded_for_notes_only")
    if confidence < 0.35:
        return out("drop", "confidence_below_floor")

    can_card = score >= s["card_threshold"]
    if s["dnd"]:
        return out("card" if can_card else "passive", "do_not_disturb_silent_card")
    if mode == "called_on":
        return out("passive", "called_on_mode_waits_for_call")
    if mode == "hold":
        return out("card" if can_card else "passive", "hold_mode_needs_user_approval")

    # interject mode
    blockers = []
    if priority not in ("critical", "important"):
        blockers.append("priority_too_low_to_interject")
    if confidence < s["confidence_threshold"]:
        blockers.append("confidence_below_threshold")
    if score < s["interject_threshold"]:
        blockers.append("score_below_threshold")
    if ctx.delivered_count >= s["max_interruptions"]:
        blockers.append("max_interruptions_reached")
    if ctx.user_speaking:
        blockers.append("user_is_speaking")
    if (priority != "critical" and ctx.last_delivered_ms is not None
            and ctx.now_ms - ctx.last_delivered_ms < s["cooldown_sec"] * 1000):
        blockers.append("cooldown_active")
    if blockers:
        reasons.extend(blockers)
        return out("card" if can_card else "passive", "interject_blocked_downgraded_to_card")
    return out("deliver", "interject_all_gates_passed")
