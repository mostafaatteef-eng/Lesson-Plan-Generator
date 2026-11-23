"""PDF fidelity regression tests: no fake document exports or invented visual scores."""
import io

import fitz
import numpy as np
import pytest

from app.engines.render_qa_engine import _global_ssim_percent, compute_visual_diff
from app import main as legacy


def _pdf_bytes(text="Sample"):
    d = fitz.open()
    page = d.new_page(width=595, height=842)
    page.insert_text((70, 100), text)
    output = d.tobytes()
    d.close()
    return output


def test_global_ssim_identical_images():
    pixels = np.arange(100, dtype=np.uint8).reshape(10, 10)
    assert _global_ssim_percent(pixels, pixels) == 100.0


def test_global_ssim_mismatched_images():
    pixels = np.zeros((10, 10), dtype=np.uint8)
    inverted = np.full((10, 10), 255, dtype=np.uint8)
    assert _global_ssim_percent(pixels, inverted) < 100.0


def test_reference_pdf_identical_reports_true_similarity():
    original = _pdf_bytes("A lesson")
    pages, _, _ = compute_visual_diff(original, original, 1, [])
    assert len(pages) == 1
    assert pages[0].structural_similarity_pct == 100.0
    assert pages[0].pixel_diff_pct == 0.0


def test_without_reference_does_not_invent_similarity():
    pages, _, _ = compute_visual_diff(_pdf_bytes(), None, 1, [])
    assert pages[0].structural_similarity_pct == 0.0
    assert "unavailable" in " ".join(pages[0].notes)


def test_legacy_pdf_conversion_failure_is_not_replaced(monkeypatch):
    def failure(_):
        raise FileNotFoundError("LibreOffice unavailable")
    monkeypatch.setattr(legacy, "render_docx_to_pdf_libreoffice", failure)
    with pytest.raises(FileNotFoundError, match="LibreOffice"):
        legacy._render_pdf_with_fallback(b"not-a-docx", None)


def test_footer_only_fifth_page_is_detected():
    from app.engines.render_qa_engine import trailing_page_is_footer_only
    doc = fitz.open()
    for i in range(4):
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 110), f"Lesson content page {i + 1}")
    last = doc.new_page(width=595, height=842)
    last.insert_text((40, 820), "5 of 5 - copyright")
    data = doc.tobytes()
    doc.close()
    assert trailing_page_is_footer_only(data)


def test_real_content_on_fifth_page_is_not_footer_only():
    from app.engines.render_qa_engine import trailing_page_is_footer_only
    doc = fitz.open()
    for _ in range(4):
        doc.new_page(width=595, height=842)
    last = doc.new_page(width=595, height=842)
    last.insert_text((40, 110), "Actual assessment questions")
    data = doc.tobytes()
    doc.close()
    assert not trailing_page_is_footer_only(data)
