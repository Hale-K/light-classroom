import pytest

from app.services.scheduling.generate_jobs import (
    GenerateBusy,
    MAX_ACTIVE_GENERATES,
    reset_generate_slots,
    release_generate_slot,
    try_acquire_generate_slot,
)


@pytest.fixture(autouse=True)
def _clear_slots():
    reset_generate_slots()
    yield
    reset_generate_slots()


def test_same_school_second_generate_is_rejected():
    try_acquire_generate_slot(1)
    with pytest.raises(GenerateBusy, match="本校已有课表正在生成"):
        try_acquire_generate_slot(1)
    release_generate_slot(1)
    try_acquire_generate_slot(1)
    release_generate_slot(1)


def test_global_cap_rejects_instead_of_starting_more_solvers():
    for tenant_id in range(1, MAX_ACTIVE_GENERATES + 1):
        try_acquire_generate_slot(tenant_id)
    with pytest.raises(GenerateBusy, match="排课生成繁忙"):
        try_acquire_generate_slot(MAX_ACTIVE_GENERATES + 1)
    release_generate_slot(1)
    try_acquire_generate_slot(MAX_ACTIVE_GENERATES + 1)
