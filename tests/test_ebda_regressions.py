"""Regression checks for EBDA production defaults and source-verification integrity."""
from app.engines.ai_engine import _verify_excerpt
from app.flask_app import InstitutionSettings


def test_school_defaults_match_2026_2027():
    settings = InstitutionSettings()
    assert settings.default_academic_year == "٢٠٢٦-٢٠٢٧"
    assert settings.default_duration_minutes == 50


def test_verbatim_excerpt_accepts_line_wrapping():
    source = "الذكاء الاصطناعي يساعد\nفي تحليل البيانات داخل المؤسسات."
    assert _verify_excerpt("الذكاء الاصطناعي يساعد في تحليل البيانات", source)


def test_partial_word_overlap_is_not_verbatim_evidence():
    source = "الذكاء الاصطناعي يساعد في تحليل البيانات داخل المؤسسات."
    assert not _verify_excerpt("الذكاء الاصطناعي يساعد المؤسسات في تحليل البيانات", source)


def test_missing_and_short_excerpts_are_not_verified():
    assert not _verify_excerpt("غير موجود في المنهج", "المحتوى مختلف تمامًا")
    assert not _verify_excerpt("مادة", "مادة")
