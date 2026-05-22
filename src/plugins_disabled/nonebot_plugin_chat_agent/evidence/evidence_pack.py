from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class EvidenceItem:
    source_type: str
    title: str
    content: str
    score: float = 0.0
    confidence: str = "medium"
    freshness: str | None = None
    source: str | None = None
    answer_hint: str | None = None
    metadata: Mapping[str, Any] | None = None


def _normalize_text(value: object, max_chars: int) -> str:
    text = str(value or "").strip()
    if max_chars <= 0:
        return ""
    return text[:max_chars]


def _normalize_confidence(value: str | None) -> str:
    v = str(value or "").strip().lower()
    if v in {"high", "medium", "low"}:
        return v
    return "medium"


def _confidence_weight(confidence: str) -> float:
    c = _normalize_confidence(confidence)
    if c == "high":
        return 1.0
    if c == "low":
        return 0.25
    return 0.6


def _source_type_weight(source_type: str) -> float:
    key = str(source_type or "").strip().lower()
    mapping = {
        "official_web": 1.0,
        "cache": 0.95,
        "knowledge_pack": 0.85,
        "skill": 0.75,
        "memory": 0.65,
        "history": 0.6,
        "web": 0.55,
        "retrieval": 0.5,
    }
    return float(mapping.get(key, 0.4))


def rank_evidence_items(items: Sequence[EvidenceItem], limit: int = 5) -> list[EvidenceItem]:
    use_limit = max(1, int(limit))
    cleaned: list[EvidenceItem] = []
    for item in items or ():
        content = _normalize_text(getattr(item, "content", ""), 4000)
        if not content:
            continue
        cleaned.append(item)

    def _sort_key(item: EvidenceItem) -> tuple[float, float, str, str]:
        score = float(getattr(item, "score", 0.0) or 0.0)
        final_score = score + _confidence_weight(getattr(item, "confidence", "medium")) + _source_type_weight(
            getattr(item, "source_type", "")
        )
        return (-final_score, -score, str(getattr(item, "source_type", "")), str(getattr(item, "title", "")))

    ranked = sorted(cleaned, key=_sort_key)
    return list(ranked[:use_limit])


def render_evidence_context(
    items: Sequence[EvidenceItem],
    *,
    budget_chars: int = 1500,
    limit: int = 5,
) -> str:
    if budget_chars <= 0:
        return ""
    ranked = rank_evidence_items(items, limit=limit)
    if not ranked:
        return ""

    out_lines = ["Known evidence:"]
    for idx, item in enumerate(ranked, start=1):
        block = [
            f"[{idx}] source_type={_normalize_text(item.source_type, 40)} confidence={_normalize_confidence(item.confidence)} score={float(item.score or 0.0):.2f}",
            f"title: {_normalize_text(item.title, 180)}",
            f"content: {_normalize_text(item.content, 300)}",
        ]
        src = _normalize_text(item.source, 260)
        if src:
            block.append(f"source: {src}")
        fresh = _normalize_text(item.freshness, 80)
        if fresh:
            block.append(f"freshness: {fresh}")
        hint = _normalize_text(item.answer_hint, 200)
        if hint:
            block.append(f"hint: {hint}")

        block_text = "\n".join(block)
        candidate = "\n".join(out_lines + [block_text, ""])
        if len(candidate) > budget_chars:
            break
        out_lines.append(block_text)
        out_lines.append("")

    rules = [
        "Answer rules:",
        "- Use only the known evidence above.",
        "- If evidence is insufficient, say you are not sure.",
        "- Do not invent facts not present in evidence.",
    ]
    candidate_with_rules = "\n".join(out_lines + rules).strip()
    if len(candidate_with_rules) <= budget_chars:
        return candidate_with_rules
    base = "\n".join(out_lines).strip()
    return base[:budget_chars]


def has_high_confidence_evidence(items: Sequence[EvidenceItem], threshold: float = 0.7) -> bool:
    th = float(threshold)
    for item in items or ():
        conf = _normalize_confidence(getattr(item, "confidence", "medium"))
        if conf != "high":
            continue
        source_type = str(getattr(item, "source_type", "")).strip().lower()
        score = float(getattr(item, "score", 0.0) or 0.0)
        if score >= th:
            return True
        if source_type in {"official_web", "cache"}:
            return True
    return False
