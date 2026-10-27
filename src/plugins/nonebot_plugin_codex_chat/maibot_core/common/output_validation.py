"""Conservative validation for model-generated chat text."""

import re

CONTROL_SUFFIXES = frozenset({"finish", "missing", "error", "done"})
_CONTROL_SUFFIX = re.compile(r"_([a-zA-Z]+)$")
_SPACED_CONTROL_SUFFIX = re.compile(r"(?<=[\u3400-\u9fff])[ \t]+([a-zA-Z]+)$")


def invalid_output_reason(text: str) -> str | None:
    match = _CONTROL_SUFFIX.search(text.strip())
    if match and match.group(1).lower() in CONTROL_SUFFIXES:
        return f"internal_control_suffix:{match.group(1).lower()}"
    spaced_match = _SPACED_CONTROL_SUFFIX.search(text.strip())
    if spaced_match and spaced_match.group(1).lower() in CONTROL_SUFFIXES:
        return f"spaced_control_suffix:{spaced_match.group(1).lower()}"
    if any("\u0530" <= char <= "\u058f" for char in text):
        return "unexpected_armenian_script"
    return None
