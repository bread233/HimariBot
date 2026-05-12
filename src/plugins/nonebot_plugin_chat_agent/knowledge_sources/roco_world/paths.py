from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RocoWorldPaths:
    root: Path
    source_dir: Path
    assets_dir: Path
    images_dir: Path
    state_file: Path
    records_file: Path


def get_roco_world_paths(root: Path | None = None) -> RocoWorldPaths:
    base = root or Path("data/nonebot_chat_agent/knowledge_sources/roco_world")
    source_dir = base / "source"
    assets_dir = base / "assets"
    images_dir = assets_dir / "images"
    return RocoWorldPaths(
        root=base,
        source_dir=source_dir,
        assets_dir=assets_dir,
        images_dir=images_dir,
        state_file=source_dir / "sync_state.json",
        records_file=source_dir / "records.jsonl",
    )

