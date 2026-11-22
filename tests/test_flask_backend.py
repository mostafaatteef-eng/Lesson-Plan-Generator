"""Functional tests for the Flask WSGI backend (app/flask_app.py).

Covers the security model (passcode gate, rate limiting, secure-by-default),
the honest rules-based fallback generation, and download behaviour.
Run: pytest tests/test_flask_backend.py
"""
from __future__ import annotations

import io

import pytest
from docx import Document

from app import flask_app as fa

PASSCODE = "test-pass-123"
HEADERS = {"X-App-Passcode": PASSCODE}

TXT = (
    "الوحدة الأولى: مقدمة في البرمجة\n"
    "الدرس الأول: المتغيرات وأنواع البيانات\n"
    "المتغير هو مساحة تخزين لها اسم. أنواع البيانات تشمل النصوص والأرقام. يستخدم المبرمج الجمل الشرطية للتحكم.\n"
    "الدرس الثاني: الجمل الشرطية\n"
    "تنفذ الجملة الشرطية كودا عند تحقق شرط معين."
).encode()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(fa, "APP_PASSCODE", PASSCODE)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    fa._PASSCODE_FAILURES.clear()
    fa.UNITS.clear()
    fa.TEMPLATES.clear()
    fa.PLANS.clear()
    fa.BATCHES.clear()
    return fa.application.test_client()


def _sample_docx() -> bytes:
    buf = io.BytesIO()
    d = Document()
    t = d.add_table(rows=3, cols=2)
    t.rows[0].cells[0].text = "الدرس"
    d.save(buf)
    return buf.getvalue()


def _upload_unit(client):
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(TXT), "unit.txt")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 200
    return r.get_json()


def _upload_template(client):
    r = client.post(
        "/api/template/upload",
        data={"docx": (io.BytesIO(_sample_docx()), "t.docx")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 200
    return r.get_json()


def _context(unit, tpl):
    return {
        "unit_id": unit["unit_id"],
        "lesson_id": unit["lessons"][0]["lesson_id"],
        "template_id": tpl["template_id"],
        "school_name": "مدرسة ابدأ",
        "teacher_name": "أ. مصطفى",
        "job_title": "معلم أول",
        "program_or_course": "الذكاء الاصطناعي",
        "grade_level": "الثاني الثانوي",
        "academic_year": "2025-2026",
        "branch": "AI",
        "total_duration_minutes": 45,
    }


def test_health_has_no_store_counts(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.get_json()
    assert body["status"] == "ok"
    assert not any("count" in k or "stored" in k for k in body)


def test_cors_only_allowed_origin(client):
    r = client.get("/api/health", headers={"Origin": "https://mostafaatteef-eng.github.io"})
    assert r.headers.get("Access-Control-Allow-Origin") == "https://mostafaatteef-eng.github.io"
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.headers.get("Access-Control-Allow-Origin") is None


def test_mutations_require_passcode(client):
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(TXT), "unit.txt")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 401
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(TXT), "unit.txt")},
        content_type="multipart/form-data",
        headers={"X-App-Passcode": "wrong"},
    )
    assert r.status_code == 401


def test_mutations_disabled_without_server_passcode(client, monkeypatch):
    monkeypatch.setattr(fa, "APP_PASSCODE", "")
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(TXT), "unit.txt")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 503


def test_passcode_rate_limited(client):
    for _ in range(5):
        client.put("/api/settings", json={}, headers={"X-App-Passcode": "bad"})
    r = client.put("/api/settings", json={}, headers={"X-App-Passcode": "bad"})
    assert r.status_code == 429


def test_rules_fallback_generation_end_to_end(client):
    unit = _upload_unit(client)
    tpl = _upload_template(client)
    r = client.post("/api/generate", json=_context(unit, tpl), headers=HEADERS)
    assert r.status_code == 200
    rec = r.get_json()
    assert rec["generation_mode"] == "rules_fallback"
    assert rec["generation_label"]  # clearly labeled, never presented as AI
    payload = rec["payload"]
    assert payload["lesson_elements"]
    assert sum(e["duration_minutes"] for e in payload["lesson_elements"]) == 45
    assert payload["missing_curriculum_notes"]
    pid = rec["plan_id"]
    r = client.get(f"/api/download/{pid}/docx")
    assert r.status_code == 200 and len(r.data) > 1000
    r = client.get(f"/api/download/{pid}/pdf")
    if rec["pdf_available"]:
        assert r.status_code == 200
        assert r.data[:4] == b"%PDF"
    else:
        assert r.status_code == 409  # honest blocked status, never a placeholder


def test_regenerate_fields_requires_ai_key(client):
    unit = _upload_unit(client)
    tpl = _upload_template(client)
    rec = client.post("/api/generate", json=_context(unit, tpl), headers=HEADERS).get_json()
    r = client.post(
        "/api/regenerate-fields",
        json={"plan_id": rec["plan_id"], "field_keys": ["warm_up"]},
        headers=HEADERS,
    )
    assert r.status_code == 503


def test_deletes_are_real(client):
    unit = _upload_unit(client)
    r = client.delete(f"/api/curriculum/{unit['unit_id']}", headers=HEADERS)
    assert r.status_code == 200
    r = client.put(
        f"/api/curriculum/{unit['unit_id']}/boundaries", json={"lessons": []}, headers=HEADERS
    )
    assert r.status_code == 404
