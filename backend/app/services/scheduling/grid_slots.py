"""Resolve concrete grade slots for each leg of a two-week timetable."""


def slot_type(grid: dict, weekday: int, period: int, parity: str) -> str:
    for slot in grid.get('slot_overrides', []):
        if (slot['weekday'], slot['period'], slot['week_parity']) == (weekday, period, parity):
            return slot['slot_type']
    if period <= grid['daily_periods'][weekday - 1]:
        return 'daytime'
    start = grid.get('evening_start_period')
    if start and start <= period < start + grid[f'evening_daily_periods_{parity}'][weekday - 1]:
        return 'evening'
    return 'disabled'


def allowed_slots(grid: dict, kind: str) -> dict[str, set[tuple[int, int]]]:
    return {parity: {(day, period) for day in range(1, 8) for period in range(1, 13)
                     if slot_type(grid, day, period, parity) == kind} for parity in ('odd', 'even')}


def item_matches_grid(grid: dict, weekday: int, period: int, parity: str) -> bool:
    legs = ('odd', 'even') if parity == 'all' else (parity,)
    return all(slot_type(grid, weekday, period, leg) != 'disabled' for leg in legs)
