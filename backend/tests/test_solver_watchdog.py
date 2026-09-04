from app.services.scheduling.solver_watchdog import solve_with_stop_deadline


def test_watchdog_calls_stop_search_after_deadline():
    class FakeSolver:
        def __init__(self) -> None:
            self.stopped = 0

        def StopSearch(self) -> None:
            self.stopped += 1

    solver = FakeSolver()
    solve_with_stop_deadline(solver, lambda: "ok", max_time_seconds=60, grace_seconds=1)
    assert solver.stopped == 0


def test_watchdog_stop_search_when_solve_overruns():
    import threading

    class FakeSolver:
        def __init__(self) -> None:
            self.stopped = 0
            self._event = threading.Event()

        def StopSearch(self) -> None:
            self.stopped += 1
            self._event.set()

        def run(self) -> str:
            self._event.wait(timeout=2.0)
            return "stopped"

    solver = FakeSolver()
    result = solve_with_stop_deadline(
        solver, solver.run, max_time_seconds=0.05, grace_seconds=0.05,
    )
    assert result == "stopped"
    assert solver.stopped >= 1


import pytest

from app.workers.scheduling.generate import WorkerTimeout, run_in_thread


@pytest.mark.asyncio
async def test_worker_thread_timeout_raises():
    def _block() -> None:
        import time
        time.sleep(1)

    with pytest.raises(WorkerTimeout):
        await run_in_thread(_block, timeout=0.05, label="测试")


def test_cpsat_retry_seeds_are_stable_and_not_arithmetic():
    from app.api.v1.scheduling import _cpsat_retry_seeds

    first = _cpsat_retry_seeds(42, 8)
    again = _cpsat_retry_seeds(42, 8)
    other = _cpsat_retry_seeds(43, 8)
    assert first == again
    assert len(set(first)) == 8
    assert first[0] == 42
    assert first != [42 + i * 97 for i in range(8)]
    assert first != other
