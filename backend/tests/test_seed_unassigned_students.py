from scripts.seed_unassigned_campus_students import grade_population


def test_5000_students_are_balanced_across_three_grades():
    counts = grade_population(5000, 3)

    assert counts == [1667, 1667, 1666]
    assert sum(counts) == 5000


def test_grade_population_differs_by_at_most_one_student():
    counts = grade_population(5000, 3)

    assert max(counts) - min(counts) <= 1
