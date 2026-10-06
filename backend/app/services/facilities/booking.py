"""Shared conflict rules for teaching and exam room occupation."""
from datetime import datetime


def periods_overlap(
    start_a: datetime, end_a: datetime, start_b: datetime, end_b: datetime,
) -> bool:
    return start_a < end_b and start_b < end_a
