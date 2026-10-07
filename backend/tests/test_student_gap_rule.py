from app.services.scheduling.walk_recommendation import recommend_walk_slots
from app.services.scheduling.student_gaps import count_student_gaps
from app.services.scheduling.rules import RuleDefinition, RuleGroupDocument, compile_rule_group, rules_for_schedule, evaluate_rule_group


def test_self_study_fills_selected_slots_separately_by_parity():
    from app.services.scheduling.student_gaps import build_student_self_study
    occupied = {'odd': {100: {(1, 2), (1, 8)}}, 'even': {100: {(1, 1)}}}
    studies = build_student_self_study(occupied, {1: [1, 2, 3]})
    assert studies == {'odd': {100: {(1, 1), (1, 3)}}, 'even': {100: {(1, 2), (1, 3)}}}
    assert occupied['odd'][100] == {(1, 2), (1, 8)}


def test_full_day_rule_requires_explicit_self_study_and_rejects_overlap():
    rule = RuleDefinition(id='full', title='学生课位排满', code='student_contiguous',
        priority='hard', schedule_scope='walk', target={'type': 'global'},
        weekdays=[1], periods=[1, 2, 3], params={'fill_self_study': True})
    group = RuleGroupDocument(id='g', name='g', academic_year='2026-2027', term='2', rules=[rule])
    assert compile_rule_group(group)[0].status == 'ready'
    occupied = {'odd': {100: {(1, 2)}}, 'even': {100: {(1, 2)}}}
    assert not evaluate_rule_group(group, [], schedule_mode='walk', student_occupied_by_parity=occupied).valid
    studies = {parity: {100: {(1, 1), (1, 3)}} for parity in occupied}
    result = evaluate_rule_group(group, [], schedule_mode='walk', student_occupied_by_parity=occupied,
        student_self_study_by_parity=studies)
    assert result.valid
    assert result.results[0].metrics['student_self_study'] == 4
    studies['odd'][100].add((1, 2))
    assert not evaluate_rule_group(group, [], schedule_mode='walk', student_occupied_by_parity=occupied,
        student_self_study_by_parity=studies).valid


def test_self_study_does_not_replace_walk_hours_or_modify_public_schedule():
    result = recommend_walk_slots(
        classes=[dict(id=1, name='生物', teacher_id=10, weekly_periods=1)],
        members=[(1, 100)], rooms=[dict(id=1, name='A', capacity=40)],
        slots=[(1, 1)], blocked_students={100: {(1, 3)}},
        student_self_study_periods={1: [1, 2, 3]},
    )
    assert result['status'] == 'feasible'
    assert result['placements'][0]['period'] == 1
    assert len(result['placements']) == 1
    assert result['student_self_study_count'] == 2  # 单双周各第2节


def test_personal_timetable_preserves_courses_and_adds_only_empty_self_study():
    from app.services.scheduling.student_gaps import complete_student_timetable
    import pytest
    lesson = dict(id=1, class_id=717, academic_year='2026-2027', term='2',
        subject_id=1, weekday=1, period=2, week_parity='odd')
    result = complete_student_timetable([lesson], {1: [1, 2, 3]},
        dict(class_id=717, class_name='高一（1）班', academic_year='2026-2027', term='2'))
    assert lesson in result
    studies = [entry for entry in result if entry.get('is_self_study')]
    assert len(studies) == 3  # 两个整周空位＋第2节双周
    assert any(entry['period'] == 2 and entry['week_parity'] == 'even' for entry in studies)
    assert all(entry['teacher_id'] is None and entry['subject_id'] == 0 for entry in studies)
    with pytest.raises(ValueError, match='冲突'):
        complete_student_timetable([lesson, dict(lesson, id=2)], {1: [1, 2, 3]}, {})


def test_gap_optimization_joins_public_and_walk_courses():
    options = dict(
        classes=[dict(id=1, name='生物', teacher_id=10, weekly_periods=1)],
        members=[(1, 100)], rooms=[dict(id=1, name='A', capacity=40)],
        slots=[(1, 2), (1, 3)], blocked_students={100: {(1, 4)}},
    )
    baseline = recommend_walk_slots(**options)
    optimized = recommend_walk_slots(**options, student_gap_weekdays=[1])
    assert baseline['placements'][0]['period'] == 2
    assert optimized['placements'][0]['period'] == 3
    assert optimized['student_gap_count'] == 0


def test_gap_objective_is_soft_and_retains_required_hours():
    result = recommend_walk_slots(
        classes=[dict(id=1, name='生物', teacher_id=10, weekly_periods=1)],
        members=[(1, 100)], rooms=[dict(id=1, name='A', capacity=40)],
        slots=[(1, 2)], blocked_students={100: {(1, 4)}}, student_gap_weekdays=[1],
    )
    assert result['status'] == 'feasible'
    assert len(result['placements']) == 1
    assert result['student_gap_count'] == 2  # 单双周各一个内部空节


def test_count_only_internal_gaps_and_keep_parities_separate():
    occupied = {'odd': {100: {(1, 2), (1, 4)}}, 'even': {100: {(1, 2)}}}
    assert count_student_gaps(occupied, [1]) == 1
    assert count_student_gaps(occupied, [2]) == 0


def test_rule_is_walk_only_soft_global_and_excluded_from_admin():
    rule = RuleDefinition(id='student-gaps', title='学生减少空档', code='student_gap_minimize',
                          priority='soft', schedule_scope='walk', target={'type': 'global'})
    group = RuleGroupDocument(id='g', name='g', academic_year='2026-2027', term='2', rules=[rule])
    assert compile_rule_group(group)[0].status == 'ready'
    assert rules_for_schedule(group, 'admin').rules == []
    for update in ({'priority': 'hard'}, {'schedule_scope': 'all'}, {'period_scope': 'evening'}):
        invalid = group.model_copy(update={'rules': [rule.model_copy(update=update)]})
        assert compile_rule_group(invalid)[0].status == 'unresolved'


def test_rule_evaluation_reports_real_combined_gaps_not_assumed_success():
    rule = RuleDefinition(id='gaps', title='学生减少空档', code='student_gap_minimize',
                          priority='soft', schedule_scope='walk', target={'type': 'global'}, weekdays=[1])
    group = RuleGroupDocument(id='g', name='g', academic_year='2026-2027', term='2', rules=[rule])
    missing = evaluate_rule_group(group, [], schedule_mode='walk')
    assert missing.results[0].status == 'not_run'
    result = evaluate_rule_group(group, [], schedule_mode='walk',
                                student_occupied_by_parity={'odd': {100: {(1, 1), (1, 3)}}, 'even': {100: {(1, 1)}}})
    assert result.valid  # soft gaps never block generation
    assert result.results[0].metrics['student_gaps'] == 1
    assert result.results[0].penalty > 0


def test_first_seven_periods_preferred_but_late_empty_periods_allowed():
    result = recommend_walk_slots(
        classes=[dict(id=1, name='生物', teacher_id=10, weekly_periods=1)],
        members=[(1, 100)], rooms=[dict(id=1, name='A', capacity=40)],
        slots=[(1, 7), (1, 8)], blocked_students={100: {(1, p) for p in range(1, 7)}},
        student_gap_weekdays=[1], student_gap_periods={1: list(range(1, 8))},
    )
    assert result['placements'][0]['period'] == 7
    assert result['student_unfilled_count'] == 0
    assert result['student_gap_count'] == 0


def test_contiguous_rule_leaves_only_trailing_empty_periods():
    result = recommend_walk_slots(
        classes=[dict(id=1, name='生物', teacher_id=10, weekly_periods=1)],
        members=[(1, 100)], rooms=[dict(id=1, name='A', capacity=40)],
        slots=[(1, 2), (1, 4), (1, 8)], blocked_students={100: {(1, 1)}},
        student_contiguous_periods={1: list(range(1, 8))},
    )
    assert result['status'] == 'feasible'
    assert result['placements'][0]['period'] == 2


def test_contiguous_rule_rejects_public_holes_without_changing_fixed_courses():
    result = recommend_walk_slots(
        classes=[dict(id=1, name='生物', teacher_id=10, weekly_periods=1)],
        members=[(1, 100)], rooms=[dict(id=1, name='A', capacity=40)],
        slots=[(1, 1), (1, 2)], blocked_students={100: {(1, 3)}},
        student_contiguous_periods={1: list(range(1, 8))},
    )
    assert result['status'] == 'infeasible'


def test_contiguous_rule_compilation_and_parity_validation():
    rule = RuleDefinition(id='continuous', title='学生课程连续', code='student_contiguous',
                          priority='hard', schedule_scope='walk', target={'type': 'global'},
                          weekdays=[1], periods=list(range(1, 8)))
    group = RuleGroupDocument(id='g', name='g', academic_year='2026-2027', term='2', rules=[rule])
    assert compile_rule_group(group)[0].status == 'ready'
    assert rules_for_schedule(group, 'admin').rules == []
    for periods in ({(1, 1), (1, 2)}, set(), {(1, 8)}):
        result = evaluate_rule_group(group, [], schedule_mode='walk',
            student_occupied_by_parity={'odd': {100: periods}, 'even': {100: periods}})
        assert result.valid
    result = evaluate_rule_group(group, [], schedule_mode='walk',
        student_occupied_by_parity={'odd': {100: {(1, 1), (1, 2)}}, 'even': {100: {(1, 2)}}})
    assert not result.valid
    assert result.results[0].violation_count == 1


def test_contiguous_rule_rejects_non_prefix_periods_and_soft_priority():
    rule = RuleDefinition(id='continuous', title='学生课程连续', code='student_contiguous',
                          priority='hard', schedule_scope='walk', target={'type': 'global'}, periods=[1, 2, 3])
    for update in ({'periods': [2, 3]}, {'periods': [1, 3]}, {'priority': 'soft'}, {'schedule_scope': 'all'}):
        group = RuleGroupDocument(id='g', name='g', academic_year='2026-2027', term='2',
                                  rules=[rule.model_copy(update=update)])
        assert compile_rule_group(group)[0].status == 'unresolved'


def test_contiguous_rule_does_not_relax_student_teacher_or_room_conflicts():
    # Two courses cannot both fill the same student's single available period.
    for members, teachers, rooms in (
        ([(1, 100), (2, 100)], [10, 20], [dict(id=1, name='A', capacity=40), dict(id=2, name='B', capacity=40)]),
        ([(1, 100), (2, 200)], [10, 10], [dict(id=1, name='A', capacity=40), dict(id=2, name='B', capacity=40)]),
        ([(1, 100), (2, 200)], [10, 20], [dict(id=1, name='A', capacity=40)]),
    ):
        result = recommend_walk_slots(
            classes=[dict(id=cid, name=str(cid), teacher_id=teachers[cid - 1], weekly_periods=1) for cid in (1, 2)],
            members=members, rooms=rooms, slots=[(1, 1)], student_contiguous_periods={1: [1]},
        )
        assert result['status'] == 'infeasible'
