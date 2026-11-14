"""进程级 VLM 故障闩锁；重启后重新尝试生产 API，不修改配置。"""

_primary_vlm_failed = False


def primary_vlm_available() -> bool:
    return not _primary_vlm_failed


def mark_primary_vlm_failed() -> None:
    global _primary_vlm_failed
    _primary_vlm_failed = True
