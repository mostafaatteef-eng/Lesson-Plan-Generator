"""Ensure the compact cover's teacher-name field is recognized."""
from app.engines.template_engine import _normalize_label


def test_teacher_name_label_is_normalized():
    assert _normalize_label("اسم المعلم", {}) == "teacher_name"
    assert _normalize_label("الاسم", {}) == "teacher_name"
