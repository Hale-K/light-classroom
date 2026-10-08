from copy import deepcopy


def test_preview_displays_candidate_lessons_and_roster_without_mutation():
    from app.services.scheduling.walk_regroup_save import candidate_display
    candidate = {'classes': [{'id': 8, 'subject_id': 2, 'size': 1, 'capacity': 45}],
        'members': [(8, 10)], 'admin_by_student': {10: 101},
        'calendar': {'public': [{'class_id': 101, 'subject_id': 1, 'teacher_id': 3,
            'weekday': 1, 'period': 1, 'room': '教室一'}]},
        'placements': [{'teaching_class_id': 8, 'subject_id': 2, 'teacher_id': 4,
            'weekday': 1, 'period': 2, 'room_id': 9}]}
    original = deepcopy(candidate)
    result = candidate_display(candidate, '高一', {1: '语文', 2: '政治'},
        {101: '高一（1）班'}, {10: '小明'}, {3: '张老师', 4: '李老师'}, {9: '教室九'},
        [(1, 1), (1, 2), (1, 3)],
        {10: {'primary_subject_name': '物理', 'secondary_subject_names': ['政治', '生物']}})
    assert [r['kind'] for r in result['lessons']] == ['admin', 'walk']
    assert result['lessons'][1]['class_name'] == '高一政治走班01'
    assert result['lessons'][1]['teacher_name'] == '李老师'
    assert result['students'] == [{'id': 10, 'name': '小明', 'class_id': 101,
        'class_name': '高一（1）班', 'teaching_class_ids': [8],
        'primary_subject_name': '物理', 'secondary_subject_names': ['政治', '生物']}]
    assert result['slots'] == [{'weekday': 1, 'period': p} for p in [1, 2, 3]]
    assert candidate == original
