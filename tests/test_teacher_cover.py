"""Ensure the compact cover's teacher-name field is recognized."""
from app.engines.template_engine import _normalize_label


def test_teacher_name_label_is_normalized():
    assert _normalize_label("اسم المعلم", {}) == "teacher_name"
    assert _normalize_label("الاسم", {}) == "teacher_name"


def test_mixed_arabic_english_spacing_preserves_code():
    from app.engines.template_engine import _normalize_mixed_script_spacing
    assert _normalize_mixed_script_spacing("متغيرات  Python") == "متغيرات Python"
    assert _normalize_mixed_script_spacing("Python  متغيرات") == "Python متغيرات"
    assert _normalize_mixed_script_spacing("x =  3") == "x =  3"
    assert _normalize_mixed_script_spacing("Python\u00a0متغيرات") == "Python متغيرات"
