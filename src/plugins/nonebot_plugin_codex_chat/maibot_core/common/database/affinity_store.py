"""Persistent per-QQ affinity operations; mood remains in memory."""

from datetime import datetime, timezone

from sqlalchemy import func, update
from sqlalchemy.dialects.sqlite import insert

from src.common.database.database import get_db_session
from src.common.database.database_model import HimariBotAffinity


def get_or_create_affinity(qq_id: str) -> HimariBotAffinity:
    """Create the initial relationship once; never reset an existing score."""
    qq_id = str(qq_id).strip()
    if not qq_id or not qq_id.isdecimal():
        raise ValueError("qq_id must be a nonempty numeric QQ identifier")
    with get_db_session() as session:
        statement = (
            insert(HimariBotAffinity)
            .values(qq_id=qq_id, affinity_score=10.0)
            .on_conflict_do_nothing(index_elements=["qq_id"])
        )
        session.execute(statement)
        session.flush()
        record = session.get(HimariBotAffinity, qq_id)
        if record is None:
            raise RuntimeError("Unable to load affinity record")
        session.expunge(record)
        return record


def change_affinity(qq_id: str, delta: float) -> HimariBotAffinity:
    """Atomically apply a bounded score delta after event evaluation."""
    import math

    if not math.isfinite(delta):
        raise ValueError("delta must be finite")
    get_or_create_affinity(qq_id)
    now = datetime.now(timezone.utc)
    with get_db_session() as session:
        session.execute(
            update(HimariBotAffinity)
            .where(HimariBotAffinity.qq_id == str(qq_id).strip())
            .values(
                affinity_score=func.min(
                    100.0, func.max(-20.0, HimariBotAffinity.affinity_score + delta)
                ),
                interaction_count=HimariBotAffinity.interaction_count + 1,
                last_interaction_at=now,
                updated_at=now,
            )
        )
        session.flush()
        record = session.get(HimariBotAffinity, str(qq_id).strip())
        if record is None:
            raise RuntimeError("Unable to load updated affinity record")
        session.refresh(record)
        session.expunge(record)
        return record
