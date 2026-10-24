"""COLLECTION-WIRING-1：可替换的UTC服务器时钟。"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """返回带时区的当前服务端时间；用于原取得时间与协调租约。"""
    return datetime.now(timezone.utc)
