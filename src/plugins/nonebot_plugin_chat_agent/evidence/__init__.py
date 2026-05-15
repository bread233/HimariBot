from __future__ import annotations

from .official import (
    OFFICIAL_WEB_RESOLVERS,
    _resolver_pattern_hit,
    get_nodejs_latest_version,
    get_ruby_latest_version,
    resolve_official_web_answer,
)

__all__ = [
    'OFFICIAL_WEB_RESOLVERS',
    '_resolver_pattern_hit',
    'get_nodejs_latest_version',
    'get_ruby_latest_version',
    'resolve_official_web_answer',
]
