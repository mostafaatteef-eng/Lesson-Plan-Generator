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


def test_capability_ids_are_full_strength(client):
    import re

    unit = _upload_unit(client)
    tpl = _upload_template(client)
    assert re.fullmatch(r"unit_[0-9a-f]{32}", unit["unit_id"])
    assert re.fullmatch(r"tpl_[0-9a-f]{32}", tpl["template_id"])
    rec = client.post("/api/generate", json=_context(unit, tpl), headers=HEADERS).get_json()
    assert re.fullmatch(r"plan_[0-9a-f]{32}", rec["plan_id"])


def test_throttle_ignores_spoofed_forwarded_for(client):
    for _ in range(5):
        client.put("/api/settings", json={}, headers={"X-App-Passcode": "bad"})
    # Attacker rotates X-Forwarded-For; the lock must still apply (keyed on peer).
    r = client.put(
        "/api/settings",
        json={},
        headers={"X-App-Passcode": "bad", "X-Forwarded-For": "203.0.113.99"},
    )
    assert r.status_code == 429


def test_upload_size_bound(client, monkeypatch):
    monkeypatch.setitem(fa.application.config, "MAX_CONTENT_LENGTH", 1024)
    big = b"x" * 2048
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(big), "big.txt")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 413


def test_batch_size_bound(client):
    unit = _upload_unit(client)
    tpl = _upload_template(client)
    ctx = _context(unit, tpl)
    body = {"lesson_ids": [unit["lessons"][0]["lesson_id"]] * 26, "base_context": ctx}
    r = client.post("/api/generate-batch", json=body, headers=HEADERS)
    assert r.status_code == 400


def test_store_cap(client, monkeypatch):
    monkeypatch.setattr(fa, "MAX_STORE_ITEMS", 1)
    _upload_unit(client)
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(TXT), "unit2.txt")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 429


def test_regenerate_blocked_with_key_but_ai_not_enabled(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    monkeypatch.delenv("ENABLE_AI_GENERATION", raising=False)

    def _boom(*a, **k):
        raise AssertionError("AI provider must never be called")

    monkeypatch.setattr(fa, "regenerate_fields", _boom)
    unit = _upload_unit(client)
    tpl = _upload_template(client)
    rec = client.post("/api/generate", json=_context(unit, tpl), headers=HEADERS).get_json()
    r = client.post(
        "/api/regenerate-fields",
        json={"plan_id": rec["plan_id"], "field_keys": ["warm_up"]},
        headers=HEADERS,
    )
    assert r.status_code == 503


def test_upload_extension_allowlist(client):
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(b"MZ..."), "evil.exe")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_store_byte_cap(client, monkeypatch):
    monkeypatch.setattr(fa, "MAX_STORE_BYTES", 100)
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(TXT), "unit.txt")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 429


def test_expired_items_are_swept(client):
    unit = _upload_unit(client)
    fa.UNITS[unit["unit_id"]]["ts"] = 0  # force expiry
    r = client.put(
        f"/api/curriculum/{unit['unit_id']}/boundaries", json={"lessons": []}, headers=HEADERS
    )
    assert r.status_code == 404
    assert unit["unit_id"] not in fa.UNITS


def _make_zip(entries) -> bytes:
    import zipfile as zf_

    buf = io.BytesIO()
    with zf_.ZipFile(buf, "w", zf_.ZIP_DEFLATED) as z:
        for name, data in entries:
            z.writestr(name, data)
    return buf.getvalue()


def test_zip_bomb_rejected(client):
    bomb = _make_zip([("word/document.xml", b"0" * (50 * 1024 * 1024))])
    assert len(bomb) < 5 * 1024 * 1024  # compresses far below the ratio bound
    r = client.post(
        "/api/template/upload",
        data={"docx": (io.BytesIO(bomb), "t.docx")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_xxe_entity_rejected(client):
    xxe = _make_zip(
        [("word/document.xml", b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r/>')]
    )
    r = client.post(
        "/api/template/upload",
        data={"docx": (io.BytesIO(xxe), "t.docx")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_pdf_page_bound(client):
    import fitz

    doc = fitz.open()
    for _ in range(301):
        doc.new_page()
    pdf = doc.tobytes()
    doc.close()
    r = client.post(
        "/api/curriculum/upload",
        data={"file": (io.BytesIO(pdf), "big.pdf")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_retained_bytes_counts_parsed_objects(client, monkeypatch):
    unit = _upload_unit(client)
    tpl = _upload_template(client)
    before = fa._retained_bytes()
    client.post("/api/generate", json=_context(unit, tpl), headers=HEADERS)
    after = fa._retained_bytes()
    # Plan record, payload object and generated blobs must all be accounted.
    assert after - before > 1000


def test_reference_pdf_replacement_respects_byte_cap(client, monkeypatch):
    tpl = _upload_template(client)
    import fitz

    doc = fitz.open()
    doc.new_page()
    pdf = doc.tobytes()
    doc.close()
    monkeypatch.setattr(fa, "MAX_STORE_BYTES", fa._retained_bytes() + len(pdf) - 1)
    r = client.post(
        f"/api/template/{tpl['template_id']}/reference-pdf",
        data={"file": (io.BytesIO(pdf), "ref.pdf")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 429


def test_regenerate_respects_byte_cap(client, monkeypatch):
    unit = _upload_unit(client)
    tpl = _upload_template(client)
    rec = client.post("/api/generate", json=_context(unit, tpl), headers=HEADERS).get_json()
    # Now authorize AI and stub the provider so no paid call can happen.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    monkeypatch.setenv("ENABLE_AI_GENERATION", "1")

    class _Payload:
        def model_dump(self):
            return {}

    monkeypatch.setattr(fa, "regenerate_fields", lambda *a, **k: _Payload())
    monkeypatch.setattr(fa, "inject_lesson_plan_xml_safe", lambda *a, **k: (b"x" * 2048, {}))
    monkeypatch.setattr(fa, "_render_pdf", lambda b: (b"y" * 2048, True))
    monkeypatch.setattr(fa, "run_four_pillar_qa", lambda **k: (_ for _ in ()).throw(RuntimeError("skip")))
    monkeypatch.setattr(fa, "MAX_STORE_BYTES", 100)
    r = client.post(
        "/api/regenerate-fields",
        json={"plan_id": rec["plan_id"], "field_keys": ["warm_up"]},
        headers=HEADERS,
    )
    assert r.status_code == 429
