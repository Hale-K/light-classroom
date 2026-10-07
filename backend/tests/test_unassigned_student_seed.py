from app.services.org.seed_utils import student_name


def test_generated_names_are_unique_for_a_5000_student_campus():
    names = [student_name(index) for index in range(5000)]

    assert len(set(names)) == 5000

