from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Skill:
    key: str
    title: str
    description: str
    intent_kinds: tuple[str, ...]
    trigger_terms: tuple[str, ...]
    negative_terms: tuple[str, ...] = ()
    group_ids: tuple[str, ...] = ()
    priority: float = 1.0
    content: str = ""


def load_builtin_skills() -> list[Skill]:
    return [
        Skill(
            key="official_current_fact_resolver",
            title="Official current fact resolver",
            description="Prefer direct official resolver for latest/current/version fact questions.",
            intent_kinds=("current_fact",),
            trigger_terms=("latest", "version", "\u6700\u65b0", "\u6700\u65b0\u7248", "\u7248\u672c"),
            negative_terms=(
                "\u662f\u4ec0\u4e48",
                "\u662f\u5565",
                "\u4ec0\u4e48\u610f\u601d",
                "\u4ec0\u4e48\u662f",
                "\u4e4b\u524d",
                "\u5386\u53f2",
                "\u804a\u8fc7",
                "\u8c01\u8bf4\u8fc7",
            ),
            priority=1.2,
            content="Prefer official resolver/direct answer for current/latest/version facts. Avoid stale web pages.",
        ),
        Skill(
            key="lightweight_definition_answer",
            title="Lightweight definition answer",
            description="Use lightweight concise concept explanation path for definition questions.",
            intent_kinds=("general", "current_fact"),
            trigger_terms=(
                "\u662f\u4ec0\u4e48",
                "\u662f\u5565",
                "\u4ec0\u4e48\u610f\u601d",
                "\u4ec0\u4e48\u662f",
                "\u662f\u505a\u4ec0\u4e48\u7684",
            ),
            negative_terms=(
                "\u6700\u65b0",
                "\u6700\u65b0\u7248",
                "\u7248\u672c",
                "\u4ef7\u683c",
                "\u65b0\u95fb",
                "\u4e4b\u524d",
                "\u5386\u53f2",
                "\u804a\u8fc7",
                "\u8c01\u8bf4\u8fc7",
            ),
            priority=1.1,
            content="For definition questions, answer briefly with lightweight definition path. Do not invent version, price, news, or history.",
        ),
    ]


async def load_db_skills(config, group_id: str | None = None) -> list[Skill]:
    _ = config
    _ = group_id
    return []


def _skill_score(skill: Skill, text: str, intent_kind: str, group_id: str | None) -> float:
    if skill.group_ids and str(group_id or "").strip() not in set(skill.group_ids):
        return 0.0
    if any(term and term in text for term in skill.negative_terms):
        return 0.0

    trigger_hits = sum(1 for t in skill.trigger_terms if t and t in text)
    intent_hit = bool(intent_kind and intent_kind in skill.intent_kinds)

    if trigger_hits <= 0 and not intent_hit:
        return 0.0
    if trigger_hits <= 0 and str(intent_kind or "").strip().lower() == "general":
        return 0.0

    score = float(trigger_hits) + (2.0 if intent_hit else 0.0)
    return max(0.0, score * float(skill.priority))


async def select_relevant_skills(config, prompt, intent_kind, group_id=None, limit=3) -> list[Skill]:
    text = str(prompt or "").strip().lower()
    kind = str(intent_kind or "").strip()
    gid = str(group_id or "").strip() or None
    candidates = load_builtin_skills() + await load_db_skills(config, gid)

    scored: list[tuple[float, Skill]] = []
    for s in candidates:
        score = _skill_score(s, text, kind, gid)
        if score > 0.0:
            scored.append((score, s))

    scored.sort(key=lambda x: (-x[0], -float(x[1].priority), x[1].key))
    return [s for _, s in scored[: max(1, int(limit))]]


def render_skill_context(skills: list[Skill]) -> str:
    if not skills:
        return ""
    lines = ["Relevant skills:"]
    for s in skills[:3]:
        if s.key == "official_current_fact_resolver":
            use_when = "current/latest/version facts need authoritative source."
            guidance = "prefer official resolver/direct answer; avoid stale web pages."
        elif s.key == "lightweight_definition_answer":
            use_when = "definition questions."
            guidance = "use lightweight definition; avoid web/history/version claims."
        else:
            use_when = s.description or "general assistance."
            guidance = s.content or "follow skill guidance conservatively."
        lines.append(f"- key: {s.key}")
        lines.append(f"  use_when: {use_when}")
        lines.append(f"  guidance: {guidance}")
        lines.append("")
    out = "\n".join(lines).strip()
    if len(out) > 1200:
        out = out[:1200]
    return out
