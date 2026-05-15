from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from nonebot import logger


@dataclass
class SkillResource:
    path: str


@dataclass
class SkillDefinition:
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    body: str = ""
    file_path: str = ""
    resources: list[SkillResource] = field(default_factory=list)

    def to_catalog_entry(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "priority": int(self.priority),
            "enabled": bool(self.enabled),
            "resource_count": len(self.resources),
            "file_path": self.file_path,
        }

    def to_activation_text(self, max_body_chars: int = 4000) -> str:
        body = str(self.body or "")
        cap = max(0, int(max_body_chars))
        if len(body) > cap > 0:
            body = body[:cap]
        trigger_text = ", ".join(self.triggers) if self.triggers else "(none)"
        return (
            f"[SKILL] {self.name}\n"
            f"description: {self.description}\n"
            f"triggers: {trigger_text}\n"
            f"priority: {self.priority}\n"
            f"body:\n{body}"
        )


@dataclass
class SkillRegistry:
    skills: dict[str, SkillDefinition] = field(default_factory=dict)

    def enabled_skills(self) -> list[SkillDefinition]:
        return [skill for skill in self.skills.values() if skill.enabled]

    def match(self, prompt: str, max_active: int = 3) -> list[SkillDefinition]:
        text = str(prompt or "").strip().lower()
        if not text:
            return []
        scored: list[tuple[int, int, str, SkillDefinition]] = []
        for skill in self.enabled_skills():
            trigger_hit = any(t and t.lower() in text for t in skill.triggers)
            name_hit = bool(skill.name and skill.name.lower() in text)
            desc_hit = bool(skill.description and skill.description.lower() in text)
            if trigger_hit:
                score = 3000
            elif name_hit:
                score = 2000
            elif desc_hit:
                score = 1000
            else:
                score = 0
            if score <= 0:
                continue
            scored.append((score, int(skill.priority), skill.name, skill))
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        limit = max(0, int(max_active))
        if limit <= 0:
            return []
        return [row[3] for row in scored[:limit]]


def _parse_bool(value: str, default: bool = True) -> bool:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_frontmatter(frontmatter_text: str) -> dict:
    data: dict[str, object] = {}
    current_list_key: str | None = None
    lines = frontmatter_text.splitlines()
    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        stripped = line.strip()
        if stripped.startswith("- ") and current_list_key:
            data.setdefault(current_list_key, [])
            lst = data[current_list_key]
            if isinstance(lst, list):
                lst.append(stripped[2:].strip())
            i += 1
            continue
        current_list_key = None
        if ":" not in line:
            i += 1
            continue
        base_indent = len(line) - len(line.lstrip(" "))
        key, value = line.split(":", 1)
        k = key.strip()
        v = value.strip()
        if v in {">", "|"}:
            block_lines: list[str] = []
            j = i + 1
            while j < len(lines):
                nxt = lines[j].rstrip("\r\n")
                nxt_strip = nxt.strip()
                nxt_indent = len(nxt) - len(nxt.lstrip(" "))
                if nxt_strip and nxt_indent <= base_indent:
                    break
                if not nxt_strip:
                    block_lines.append("")
                else:
                    block_lines.append(nxt.lstrip(" "))
                j += 1
            if v == ">":
                folded = " ".join(part.strip() for part in block_lines if part.strip())
                data[k] = folded.strip()
            else:
                literal = "\n".join(block_lines).strip("\n")
                data[k] = literal
            i = j
            continue
        if v == "":
            data[k] = []
            current_list_key = k
            i += 1
            continue
        data[k] = v
        i += 1
    return data


def _collect_resources(skill_file: Path) -> list[SkillResource]:
    parent = skill_file.parent
    resources: list[SkillResource] = []
    for child in sorted(parent.iterdir(), key=lambda p: p.name):
        if child.name == "SKILL.md":
            continue
        if child.name.startswith(".") or child.name == "__pycache__":
            continue
        if not child.is_file():
            continue
        resources.append(SkillResource(path=child.name))
    return resources


def load_skill_file(path: Path) -> SkillDefinition | None:
    skill_path = Path(path)
    if not skill_path.is_file():
        return None
    try:
        text = skill_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning(f"skill_registry read failed path={skill_path} type={type(exc).__name__}")
        return None

    stripped = text.strip()
    if not stripped.startswith("---"):
        logger.warning(f"skill_registry frontmatter missing path={skill_path}")
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        logger.warning(f"skill_registry frontmatter invalid path={skill_path}")
        return None
    frontmatter_text = parts[1]
    body = parts[2].lstrip("\r\n")
    data = _parse_frontmatter(frontmatter_text)

    name = str(data.get("name", "")).strip()
    description = str(data.get("description", "")).strip()
    if not name or not description:
        logger.warning(f"skill_registry name/description missing path={skill_path}")
        return None

    triggers_raw = data.get("triggers", [])
    triggers: list[str]
    if isinstance(triggers_raw, list):
        triggers = [str(item).strip() for item in triggers_raw if str(item).strip()]
    elif isinstance(triggers_raw, str) and triggers_raw.strip():
        triggers = [triggers_raw.strip()]
    else:
        triggers = []
    try:
        priority = int(str(data.get("priority", 0)).strip() or "0")
    except Exception:
        priority = 0
    enabled = _parse_bool(str(data.get("enabled", "true")), default=True)

    return SkillDefinition(
        name=name,
        description=description,
        triggers=triggers,
        priority=priority,
        enabled=enabled,
        body=body,
        file_path=str(skill_path),
        resources=_collect_resources(skill_path),
    )


def load_skill_registry(skills_dir: str | Path) -> SkillRegistry:
    root = Path(skills_dir)
    registry = SkillRegistry()
    if not root.exists() or not root.is_dir():
        return registry

    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name == "__pycache__":
            continue
        skill_file = entry / "SKILL.md"
        skill = load_skill_file(skill_file)
        if skill is None:
            continue
        old = registry.skills.get(skill.name)
        if old is None:
            registry.skills[skill.name] = skill
            continue
        if skill.priority > old.priority:
            logger.warning(
                f"skill_registry duplicate_name replace name={skill.name} old_priority={old.priority} new_priority={skill.priority}"
            )
            registry.skills[skill.name] = skill
        else:
            logger.warning(
                f"skill_registry duplicate_name keep_first name={skill.name} old_priority={old.priority} new_priority={skill.priority}"
            )
    return registry
