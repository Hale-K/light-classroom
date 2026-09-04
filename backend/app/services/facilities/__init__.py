"""场室：教室分配规则与占用冲突。"""

from app.services.facilities.allocation import room_matches_rule
from app.services.facilities.booking import periods_overlap

__all__ = ["periods_overlap", "room_matches_rule"]
