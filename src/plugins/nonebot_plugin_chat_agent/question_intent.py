from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionIntent:
    is_question_like: bool
    category: str
    should_use_evidence: bool
    web_eligible: bool
    matched_terms: tuple[str, ...] = ()


def detect_question_like(prompt: str) -> QuestionIntent:
    text = str(prompt or "").strip().lower()
    if not text:
        return QuestionIntent(False, "none", False, False, ())

    history_terms = (
        "\u4e4b\u524d",
        "\u521a\u624d",
        "\u4e0a\u6b21",
        "\u5386\u53f2",
        "\u804a\u8fc7",
        "\u8c01\u8bf4\u8fc7",
        "\u6211\u8bf4\u8fc7",
        "\u4f60\u8bb0\u5f97",
        "\u6211\u4eec\u8ba8\u8bba\u8fc7",
    )
    current_fact_terms = (
        "\u6700\u65b0",
        "\u6700\u65b0\u7248",
        "\u5f53\u524d",
        "\u73b0\u5728",
        "\u4eca\u5929",
        "\u4eca\u5e74",
        "\u7248\u672c",
        "\u4ef7\u683c",
        "\u591a\u5c11\u94b1",
        "\u53d1\u5e03",
        "\u66f4\u65b0",
        "\u65b0\u95fb",
        "\u516c\u544a",
        "\u72b6\u6001",
    )
    recommendation_terms = (
        "\u63a8\u8350",
        "\u5efa\u8bae",
        "\u600e\u4e48\u9009",
        "\u9009\u4ec0\u4e48",
        "\u9009\u54ea\u4e2a",
        "\u54ea\u4e2a\u597d",
        "\u66f4\u597d",
        "\u503c\u4e0d\u503c\u5f97",
        "\u9002\u5408",
        "\u65b0\u624b",
        "\u8def\u7ebf",
        "\u73a9\u6cd5",
        "\u653b\u7565",
        "\u914d\u7f6e",
        "\u65b9\u6848",
    )
    comparison_terms = (
        "\u8fd8\u662f",
        "\u54ea\u4e2a\u597d\u73a9",
        "\u66f4\u597d\u73a9",
        "\u5bf9\u6bd4",
        "\u533a\u522b",
        "vs",
    )
    troubleshooting_terms = (
        "\u62a5\u9519",
        "\u5931\u8d25",
        "\u4e0d\u884c",
        "\u6ca1\u53cd\u5e94",
        "\u600e\u4e48\u4fee",
        "\u5982\u4f55\u89e6\u53d1",
        "\u5e2e\u6211\u770b",
        "\u5e2e\u6211\u67e5",
        "\u5e2e\u6211\u5206\u6790",
        "\u8fd9\u662f\u4ec0\u4e48\u610f\u601d",
    )
    definition_terms = (
        "\u662f\u4ec0\u4e48",
        "\u662f\u5565",
        "\u4ec0\u4e48\u662f",
        "\u4ec0\u4e48\u610f\u601d",
        "\u662f\u505a\u4ec0\u4e48\u7684",
    )
    general_question_terms = (
        "\u4ec0\u4e48",
        "\u4e3a\u5565",
        "\u4e3a\u4ec0\u4e48",
        "\u600e\u4e48",
        "\u548b",
        "\u5982\u4f55",
        "\u54ea\u91cc",
        "\u54ea\u4e2a",
        "\u8c01",
        "\u591a\u5c11",
        "\u51e0",
        "\u662f\u5426",
        "\u80fd\u4e0d\u80fd",
        "\u53ef\u4e0d\u53ef\u4ee5",
        "\u6709\u6ca1\u6709",
        "\u662f\u4e0d\u662f",
        "\u8981\u4e0d\u8981",
        "\u8be5\u4e0d\u8be5",
    )
    question_suffixes = (
        "\u5417",
        "\u5462",
        "\u4e48",
        "\u561b",
        "\u5bf9\u5417",
        "\u662f\u5417",
        "\u884c\u5417",
        "\u53ef\u4ee5\u5417",
        "\u597d\u7528\u5417",
        "\u9760\u8c31\u5417",
        "\u597d\u73a9\u5417",
        "\u884c\u4e0d",
        "\u53ef\u4ee5\u4e0d",
    )
    web_judgement_terms = (
        "\u80fd",
        "\u4f1a",
        "\u53ef\u4ee5",
        "\u6709\u6ca1\u6709\u673a\u4f1a",
        "\u662f\u5426",
        "\u662f\u4e0d\u662f",
        "\u503c\u4e0d\u503c\u5f97",
        "\u597d\u4e0d\u597d",
        "\u5f3a\u4e0d\u5f3a",
        "\u63a8\u8350\u5417",
        "\u9002\u5408\u5417",
    )

    def _hits(terms: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(t for t in terms if t and t in text)

    checks = (
        ("history", False, _hits(history_terms)),
        ("current_fact", True, _hits(current_fact_terms)),
        ("recommendation", True, _hits(recommendation_terms)),
        ("comparison", True, _hits(comparison_terms)),
        ("troubleshooting", True, _hits(troubleshooting_terms)),
        ("definition", False, _hits(definition_terms)),
    )
    for category, web_eligible, matched in checks:
        if matched:
            return QuestionIntent(True, category, True, web_eligible, matched)

    matched_general = _hits(general_question_terms)
    matched_suffix = tuple(s for s in question_suffixes if text.endswith(s))
    if matched_general or matched_suffix:
        matched = matched_general or matched_suffix
        matched_judgement = _hits(web_judgement_terms)
        has_modal_pattern = (
            text.endswith("\u5417")
            and any(x in text for x in ("\u80fd", "\u4f1a", "\u53ef\u4ee5", "\u662f\u5426", "\u662f\u4e0d\u662f"))
        )
        web_eligible = bool(matched_judgement or has_modal_pattern)
        merged = tuple(dict.fromkeys(matched + matched_judgement))
        return QuestionIntent(True, "general_question", True, web_eligible, merged or matched)

    return QuestionIntent(False, "none", False, False, ())
