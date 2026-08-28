import pytest
from pydantic import ValidationError

from app.api.v1.org import StudentIn
from app.models.enums import Gender


def test_student_profile_accepts_height_in_centimeters():
    student = StudentIn(name="张同学", gender=Gender.male, height_cm=172.5)

    assert student.height_cm == 172.5


def test_student_profile_rejects_an_impossible_height():
    with pytest.raises(ValidationError):
        StudentIn(name="张同学", gender=Gender.male, height_cm=20)
