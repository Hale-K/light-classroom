"""Rules shared by head-teacher configuration and class-directory views."""
from collections.abc import Iterable, Mapping


def summarize_head_teacher_assignment(
    teacher_id: int,
    class_id: int,
    assignments: Iterable[Mapping[str, int | None]],
) -> dict[str, int | None | bool]:
    """Return the teacher's current teaching load.

    A head teacher may be appointed before teaching assignments are generated.
    In that case the class load is still valid, but the own-class teaching flag
    remains false until the teaching relationship is created.
    """
    teacher_assignments = [
        item for item in assignments if item["teacher_id"] == teacher_id
    ]
    own_assignment = next(
        (item for item in teacher_assignments if item["class_id"] == class_id),
        None,
    )
    return {
        "subject_id": own_assignment["subject_id"] if own_assignment else None,
        "taught_class_count": len({item["class_id"] for item in teacher_assignments}),
        "teaches_own_class": own_assignment is not None,
    }
