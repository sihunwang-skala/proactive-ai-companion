"""Server-side UI strings (en/ko) for text the engine composes."""
S = {
    "misconception": {"en": "Possible misconception — {topic}", "ko": "개념 오류 가능성 — {topic}"},
    "think": {"en": "Think about this…", "ko": "한번 생각해 보세요…"},
    "verify": {"en": "Please verify this figure", "ko": "수치를 확인해 주세요"},
    "contradiction": {"en": "Possible contradiction", "ko": "모순 가능성"},
    "contra_body": {"en": "Earlier ({ts}) \"{old}\"; now \"{new}\" for \"{subj}\".", "ko": "앞서({ts}) \"{old}\"라고 했는데, 지금은 \"{subj}\"에 대해 \"{new}\"라고 하셨습니다."},
    "answer_sugg": {"en": "Suggested answer", "ko": "답변 제안"},
    "decision": {"en": "Decision noted", "ko": "결정사항 기록"},
    "action": {"en": "Action item noted", "ko": "할 일 기록"},
    "action_body": {"en": "{text} (owner: {owner}, deadline: {deadline})", "ko": "{text} (담당: {owner}, 기한: {deadline})"},
    "not_stated": {"en": "not stated", "ko": "언급 없음"},
    "from_doc": {"en": "From \"{doc}\": {p}", "ko": "\"{doc}\"에서: {p}"},
    "answer": {"en": "Answer", "ko": "답변"},
    "no_answer": {"en": "No answer available", "ko": "답변할 수 없음"},
    "no_answer_body": {
        "en": "I found nothing relevant in your documents and no LLM provider is configured/available. Add a document or enable a provider (see DEPLOYMENT.md).",
        "ko": "문서에서 관련 내용을 찾지 못했고 사용 가능한 LLM 제공자도 없습니다. 문서를 추가하거나 제공자를 설정해 주세요(DEPLOYMENT.md 참고)."},
    "doc_mismatch": {"en": "Your document \"{doc}\" says: \"{p}\" — the figure mentioned differs. Please verify.",
                     "ko": "문서 \"{doc}\"에는 \"{p}\"라고 되어 있어 언급된 수치와 다릅니다. 확인해 주세요."},
    "summary": {
        "en": "{n} utterances over {dur} from {sp} labelled speaker(s). {d} decision(s), {a} action item(s), {q} unresolved question(s), {c} contradiction(s), {e} possible error(s) flagged.",
        "ko": "발화 {n}건, 길이 {dur}, 화자 {sp}명. 결정 {d}건, 할 일 {a}건, 미해결 질문 {q}건, 모순 {c}건, 오류 가능성 {e}건."},
    "no_utt": {"en": "No utterances recorded.", "ko": "기록된 발화가 없습니다."},
    "fu_owner": {"en": "Assign an owner/deadline: \"{t}\"", "ko": "담당자/기한 지정 필요: \"{t}\""},
    "fu_q": {"en": "Resolve open question: \"{t}\"", "ko": "미해결 질문 처리: \"{t}\""},
}


def tr(lang: str, key: str, **kw) -> str:
    d = S[key]
    return d.get(lang, d["en"]).format(**kw)
