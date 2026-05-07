from __future__ import annotations


def _to_int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


async def get_group_info_context(bot, event, session_info: dict) -> str:
    if session_info.get("session_type") != "group":
        return ""
    group_id = _to_int(session_info.get("group_id"))
    if group_id is None:
        return ""
    try:
        info = await bot.get_group_info(group_id=group_id)
    except Exception:
        return ""
    lines = ["当前群信息："]
    if info.get("group_id") is not None:
        lines.append(f"- 群号：{info.get('group_id')}")
    if info.get("group_name"):
        lines.append(f"- 群名：{info.get('group_name')}")
    member_count = info.get("member_count")
    max_member_count = info.get("max_member_count")
    if member_count is not None and max_member_count is not None:
        lines.append(f"- 成员数：{member_count}/{max_member_count}")
    return "\n".join(lines) if len(lines) > 1 else ""


async def get_group_member_seen_context(bot, event, session_info: dict) -> str:
    if session_info.get("session_type") != "group":
        return ""
    group_id = _to_int(session_info.get("group_id"))
    user_id = _to_int(session_info.get("user_id"))
    if group_id is None or user_id is None:
        return ""
    try:
        info = await bot.get_group_member_info(group_id=group_id, user_id=user_id, no_cache=False)
    except Exception:
        return ""
    lines = ["当前发言人在群内："]
    if info.get("user_id") is not None:
        lines.append(f"- QQ：{info.get('user_id')}")
    if info.get("card"):
        lines.append(f"- 群昵称：{info.get('card')}")
    if info.get("nickname"):
        lines.append(f"- QQ昵称：{info.get('nickname')}")
    if info.get("role"):
        lines.append(f"- 身份：{info.get('role')}")
    if info.get("title"):
        lines.append(f"- 头衔：{info.get('title')}")
    return "\n".join(lines) if len(lines) > 1 else ""


async def search_group_member_candidates(bot, group_id: str, keyword: str, limit: int = 5) -> list[dict]:
    group_int = _to_int(group_id)
    if group_int is None:
        return []
    try:
        members = await bot.get_group_member_list(group_id=group_int)
    except Exception:
        return []
    needle = (keyword or "").strip().lower()
    result: list[dict] = []
    for item in members or []:
        card = str(item.get("card") or "").strip()
        nickname = str(item.get("nickname") or "").strip()
        user_id = str(item.get("user_id") or "").strip()
        role = str(item.get("role") or "").strip()
        text = " ".join([card, nickname, user_id]).lower()
        if needle and needle not in text:
            continue
        result.append({"user_id": user_id, "card": card, "nickname": nickname, "role": role})
        if len(result) >= max(1, int(limit)):
            break
    return result
