from typing import Any, Iterable


def flatten_message_components(sequences: Iterable[Any]) -> list[Any]:
    """按原顺序合并多个 MessageSequence 的全部组件。"""

    components: list[Any] = []
    for sequence in sequences:
        components.extend(list(getattr(sequence, "components", None) or []))
    return components


def all_send_results_confirmed(send_results: Any) -> bool:
    """旧式分段结果只有全部明确成功时才视为完整送达。"""

    return bool(send_results) and isinstance(send_results, list) and all(
        isinstance(item, dict) and item.get("success") is True
        for item in send_results
    )
