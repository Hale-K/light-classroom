"""教学教务：新高考走班、任教匹配、学年滚动、学籍导入。"""

from app.services.academic.auto_teaching import (
    TeacherScopeRule,
    apply_subject_periods,
    assignments_outside_rebuild_scope,
    build_auto_assignments,
    suggested_weekly_periods,
    target_class_ids,
)
from app.services.academic.gaokao import (
    SubjectChoice,
    SubjectChoicePolicy,
    form_teaching_classes,
    generate_walk_schedule,
    get_subject_choice_strategy,
    resolve_selection_phase,
)
from app.services.academic.head_teacher import summarize_head_teacher_assignment
from app.services.academic.rollover import (
    build_rollover_plan,
    next_grade_level,
    promoted_class_name,
)
from app.services.academic.student_import import (
    ImportContext,
    context_from_config,
    normalize_gender,
    parse_rows,
)
from app.services.academic.student_membership import sync_student_grade_membership

__all__ = [
    "ImportContext",
    "SubjectChoice",
    "SubjectChoicePolicy",
    "TeacherScopeRule",
    "apply_subject_periods",
    "assignments_outside_rebuild_scope",
    "build_auto_assignments",
    "build_rollover_plan",
    "context_from_config",
    "form_teaching_classes",
    "generate_walk_schedule",
    "get_subject_choice_strategy",
    "next_grade_level",
    "normalize_gender",
    "parse_rows",
    "promoted_class_name",
    "resolve_selection_phase",
    "suggested_weekly_periods",
    "summarize_head_teacher_assignment",
    "sync_student_grade_membership",
    "target_class_ids",
]
