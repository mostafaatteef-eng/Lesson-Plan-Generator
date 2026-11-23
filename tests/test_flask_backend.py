"""Functional tests for the Flask WSGI backend (app/flask_app.py).

The backend is request-scoped: it keeps NO lesson data between requests
(no curriculum/template/plan/batch stores). The browser holds uploads and
parsed data; generation requests carry their inputs and the response
carries every artifact back as base64. Store-era tests (TTL sweeps, purge
endpoints, capability downloads, store caps) were removed with the store
layer they tested; the no-retention guarantee is guarded directly by
test_no_lesson_data_stores_exist and by artifact assertions on responses.

Covers the security model (optional passcode gate, failure rate limiting,
open access by explicit product decision when no passcode is configured),
upload validation, the honest rules-based fallback generation, QA blocking,
and the single/multi-lesson response contract.
Run: pytest tests/test_flask_backend.py
"""
from __future__ import annotations

import base64
import io
import json

import pytest
from docx import Document

from app import flask_app as fa

PASSCODE = "test-pass-123"
HEADERS = {"X-App-Passcode": PASSCODE}

# Complete, valid curriculum: each lesson extract is well over the 30-word
# boundary gate so a correct generation passes QA without blocking gates.
TXT = (
    "الوحدة الأولى: مقدمة في البرمجة\n"
    "الدرس الأول: المتغيرات وأنواع البيانات\n"
    "المتغير هو مساحة تخزين لها اسم في ذاكرة الحاسوب يستخدمها البرنامج لحفظ القيم أثناء التنفيذ. "
    "أنواع البيانات تشمل النصوص والأرقام الصحيحة والأرقام العشرية والقيم المنطقية. "
    "يختار المبرمج النوع المناسب حسب طبيعة البيانات التي يعالجها برنامجه. "
    "يتدرب الطالب على تعريف متغيرات بأسماء واضحة ويستكشف أثر كل نوع على ناتج البرنامج. "
    "يربط الدرس بين المفهوم وتطبيق عملي قصير يكتب فيه الطلاب برنامجا يخزن بياناتهم ويعرضها.\n"
    "الدرس الثاني: الجمل الشرطية\n"
    "تنفذ الجملة الشرطية مجموعة من الأوامر عند تحقق شرط معين وتتجاهلها عند عدم تحققه. "
    "يشرح الطالب بنية الجملة الشرطية البسيطة والمركبة ويستخدم عوامل المقارنة والعوامل المنطقية. "
    "يكتب الطلاب برامج صغيرة تتخذ قرارات مثل التحقق من صحة المدخلات أو تقييم نتيجة اختبار. "
    "يناقش الدرس أخطاء شائعة في كتابة الشروط المتداخلة وطرق اختبارها وتصحيحها خطوة بخطوة."
).encode()

# Deliberately thin curriculum: each lesson extract is under 30 words, which
# must trip the blocking boundary gate and refuse artifact production.
TXT_THIN = (
    "الوحدة الأولى: مقدمة في البرمجة\n"
    "الدرس الأول: المتغيرات وأنواع البيانات\n"
    "المتغير هو مساحة تخزين لها اسم. أنواع البيانات تشمل النصوص والأرقام.\n"
    "الدرس الثاني: الجمل الشرطية\n"
    "تنفذ الجملة الشرطية كودا عند تحقق شرط معين."
).encode()


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(fa, "APP_PASSCODE", PASSCODE)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ENABLE_AI_GENERATION", raising=False)
    fa._PASSCODE_FAILURES.clear()
    return fa.application.test_client()


def _sample_docx() -> bytes:
    """Recognizable EBDA-style template: markers the injector actually fills."""
    buf = io.BytesIO()
    d = Document()
    t = d.add_table(rows=10, cols=2)
    rows = [
        ("عناصر الدرس", "الزمن"),
        ("1-", ""),
        ("2-", ""),
        ("3-", ""),
        ("4-", ""),
        ("5-", ""),
        ("استراتيجيات التدريس", "☐ العصف الذهني  ☐ التعلم التعاوني"),
        ("مصادر التعلم", "☐ الكتاب المدرسي"),
        ("إجراءات النشاط ١", ""),
        ("", ""),
    ]
    for (c0, c1), row in zip(rows, t.rows):
        row.cells[0].text = c0
        row.cells[1].text = c1
    d.save(buf)
    return buf.getvalue()


def _unrecognized_docx() -> bytes:
    """Bare table with no recognizable markers: must be refused, not fake-filled."""
    buf = io.BytesIO()
    d = Document()
    d.add_table(rows=3, cols=2)
    d.save(buf)
    return buf.getvalue()


def _parse_unit(client, raw=TXT, name="unit.txt"):
    r = client.post(
        "/api/curriculum/parse",
        data={"file": (io.BytesIO(raw), name)},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 200
    return r.get_json()


def _parse_template(client, docx_bytes=None):
    r = client.post(
        "/api/template/parse",
        data={"docx": (io.BytesIO(docx_bytes or _sample_docx()), "t.docx")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 200
    return r.get_json()


def _slim_unit(unit):
    """Unit metadata as the browser sends it with a generation request."""
    return {k: v for k, v in unit.items() if k not in ("lessons", "pages")}


def _generate(client, unit, lessons, template_bytes=None, context_overrides=None):
    ctx = {
        "school_name": "مدرسة ابدأ",
        "teacher_name": "أ. مصطفى",
        "job_title": "معلم أول",
        "program_or_course": "الذكاء الاصطناعي",
        "grade_level": "الثاني الثانوي",
        "academic_year": "2025-2026",
        "branch": "AI",
        "total_duration_minutes": 45,
    }
    if context_overrides:
        ctx.update(context_overrides)
    body = {"context": ctx, "unit": _slim_unit(unit), "lessons": lessons}
    return client.post(
        "/api/generate",
        data={
            "template": (io.BytesIO(template_bytes or _sample_docx()), "t.docx"),
            "request": json.dumps(body),
        },
        content_type="multipart/form-data",
        headers=HEADERS,
    )


def _b64d(s):
    return base64.b64decode(s)


# ---------------- Security model ----------------

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
    def _fresh(path):
        if "curriculum" in path:
            return path, {"file": (io.BytesIO(TXT), "unit.txt")}
        return path, {"docx": (io.BytesIO(_sample_docx()), "t.docx")}

    for path in ("/api/curriculum/parse", "/api/template/parse"):
        p, data = _fresh(path)
        r = client.post(p, data=data, content_type="multipart/form-data")
        assert r.status_code == 401, path
        p, data = _fresh(path)
        r = client.post(
            p, data=data, content_type="multipart/form-data",
            headers={"X-App-Passcode": "wrong"},
        )
        assert r.status_code == 401, path


def test_mutations_open_without_server_passcode(client, monkeypatch):
    # Explicit product decision (2026-11-23): with no APP_PASSCODE the tool
    # is open access — no credential is required for parse/generate.
    monkeypatch.setattr(fa, "APP_PASSCODE", "")
    r = client.post(
        "/api/curriculum/parse",
        data={"file": (io.BytesIO(TXT), "unit.txt")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200


def _generate_without_template(client):
    unit = _parse_unit(client)
    body = {
        "context": {
            "school_name": "مدرسة ابدأ",
            "teacher_name": "أ. مصطفى",
            "job_title": "معلم أول",
            "program_or_course": "الذكاء الاصطناعي",
            "grade_level": "الثاني الثانوي",
            "academic_year": "2025-2026",
            "branch": "AI",
            "total_duration_minutes": 45,
        },
        "unit": _slim_unit(unit),
        "lessons": unit["lessons"][:1],
    }
    return client.post(
        "/api/generate",
        data={"request": json.dumps(body)},
        content_type="multipart/form-data",
        headers=HEADERS,
    )


def test_builtin_template_fallback(client, monkeypatch, tmp_path):
    tpl = tmp_path / "builtin.docx"
    tpl.write_bytes(_sample_docx())
    monkeypatch.setattr(fa, "DEFAULT_TEMPLATE_PATH", str(tpl))
    r = client.post(
        "/api/template/parse", data={}, content_type="multipart/form-data", headers=HEADERS
    )
    assert r.status_code == 200
    health = client.get("/api/health").get_json()
    assert health["defaults"]["template"] is True
    assert health["defaults"]["reference_pdf"] is False
    # Generation without an uploaded template uses the built-in asset.
    r = _generate_without_template(client)
    assert r.status_code != 400  # never "Missing template DOCX file."


def test_builtin_template_and_reference_fallback(client, monkeypatch, tmp_path):
    from pypdf import PdfWriter

    tpl = tmp_path / "builtin.docx"
    tpl.write_bytes(_sample_docx())
    ref = tmp_path / "ref.pdf"
    writer = PdfWriter()
    writer.add_blank_page(612, 792)
    with ref.open("wb") as fh:
        writer.write(fh)
    monkeypatch.setattr(fa, "DEFAULT_TEMPLATE_PATH", str(tpl))
    monkeypatch.setattr(fa, "DEFAULT_REFERENCE_PDF_PATH", str(ref))
    # Parse with no uploaded files uses both built-in assets.
    r = client.post(
        "/api/template/parse", data={}, content_type="multipart/form-data", headers=HEADERS
    )
    assert r.status_code == 200
    health = client.get("/api/health").get_json()
    assert health["defaults"]["template"] is True
    assert health["defaults"]["reference_pdf"] is True
    r = _generate_without_template(client)
    assert r.status_code != 400


def test_missing_template_without_builtin_is_400(client, monkeypatch):
    monkeypatch.setattr(fa, "DEFAULT_TEMPLATE_PATH", "")
    unit = _parse_unit(client)
    body = {"context": {}, "unit": _slim_unit(unit), "lessons": unit["lessons"][:1]}
    r = client.post(
        "/api/generate",
        data={"request": json.dumps(body)},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_passcode_rate_limited(client):
    for _ in range(5):
        client.put("/api/settings", json={}, headers={"X-App-Passcode": "bad"})
    r = client.put("/api/settings", json={}, headers={"X-App-Passcode": "bad"})
    assert r.status_code == 429


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


# ---------------- No-retention architecture ----------------

def test_no_lesson_data_stores_exist():
    # Architectural guard: the no-retention requirement is met by having no
    # server-side lesson-data stores at all. If anyone reintroduces one, this
    # test fails.
    for store in ("UNITS", "TEMPLATES", "PLANS", "BATCHES"):
        assert not hasattr(fa, store), f"lesson-data store {store} reintroduced"


def test_parse_returns_data_but_server_keeps_nothing(client):
    unit = _parse_unit(client)
    assert unit["lessons"] and unit["lessons"][0]["raw_text"]
    # No server-side handle exists to reach this data again: the id is only a
    # client-side key, and there is no endpoint that reads stored curriculum.
    assert unit["unit_id"].startswith("unit_")
    r = client.put(
        f"/api/curriculum/{unit['unit_id']}/boundaries", json={"lessons": []}, headers=HEADERS
    )
    assert r.status_code in (404, 405)  # old store endpoints are gone


def test_old_download_and_purge_endpoints_are_gone(client):
    for path in (
        "/api/download/plan_x/docx",
        "/api/download/batch/batch_x",
        "/api/plans/plan_x/purge",
    ):
        r = client.get(path) if "purge" not in path else client.post(path, json={})
        assert r.status_code in (404, 405), path


# ---------------- Generation contract ----------------

def test_rules_fallback_generation_end_to_end(client):
    unit = _parse_unit(client)
    r = _generate(client, unit, [unit["lessons"][0]])
    assert r.status_code == 200
    rec = r.get_json()["plan"]
    assert rec["generation_mode"] == "rules_fallback"
    assert rec["generation_label"]  # clearly labeled, never presented as AI
    payload = rec["payload"]
    assert payload["lesson_elements"]
    assert sum(e["duration_minutes"] for e in payload["lesson_elements"]) == 45
    assert payload["missing_curriculum_notes"]
    # Artifacts arrive IN THE RESPONSE, not via a server-side download later.
    docx = _b64d(rec["docx_b64"])
    assert docx[:2] == b"PK" and len(docx) > 1000
    if rec["pdf_available"]:
        assert _b64d(rec["pdf_b64"])[:4] == b"%PDF"
    else:
        assert rec["pdf_b64"] is None  # honest absence, never a placeholder


def test_generate_rejects_unrecognized_template(client):
    unit = _parse_unit(client)
    r = _generate(client, unit, [unit["lessons"][0]], template_bytes=_unrecognized_docx())
    assert r.status_code == 422
    assert "القالب غير معروف" in r.get_json()["detail"]


def test_blocking_qa_returns_422_and_produces_no_artifacts(client):
    thin_unit = _parse_unit(client, raw=TXT_THIN, name="thin.txt")
    r = _generate(client, thin_unit, [thin_unit["lessons"][0]])
    assert r.status_code == 422
    body = r.get_json()
    assert body["qa_blocked"] is True
    assert body["blocking_gates"]
    assert "qa_report" in body
    # Nothing downloadable exists: no artifact fields, no plan id, no stores.
    assert "docx_b64" not in body and "pdf_b64" not in body
    assert "plan_id" not in body


def test_generate_fills_recognized_template(client):
    unit = _parse_unit(client)
    r = _generate(client, unit, [unit["lessons"][0]])
    assert r.status_code == 200
    doc = Document(io.BytesIO(_b64d(r.get_json()["plan"]["docx_b64"])))
    text = "\n".join(
        cell.text for table in doc.tables for row in table.rows for cell in row.cells
    )
    assert payload_markers_filled(text)


def test_generated_docx_has_neutral_core_properties(client):
    # Privacy: template docProps (real personal names) must never leak into a
    # generated plan.
    unit = _parse_unit(client)
    r = _generate(client, unit, [unit["lessons"][0]])
    assert r.status_code == 200
    doc = Document(io.BytesIO(_b64d(r.get_json()["plan"]["docx_b64"])))
    cp = doc.core_properties
    assert cp.author == "EBDA AI Lesson Studio"
    assert cp.last_modified_by == "EBDA AI Lesson Studio"


def payload_markers_filled(text: str) -> bool:
    # Element markers now carry real titles, not the bare "1-" placeholder.
    lines = [ln.strip() for ln in text.splitlines()]
    return any(ln.startswith("1-") and len(ln) > 3 for ln in lines)


def test_key_without_enable_flag_stays_rules_fallback(client, monkeypatch):
    # A saved key alone is not spend permission.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-dummy")
    monkeypatch.delenv("ENABLE_AI_GENERATION", raising=False)

    def _boom(*a, **k):
        raise AssertionError("AI provider must never be called")

    monkeypatch.setattr(fa, "generate_lesson_plan", _boom)
    unit = _parse_unit(client)
    r = _generate(client, unit, [unit["lessons"][0]])
    assert r.status_code == 200
    assert r.get_json()["plan"]["generation_mode"] == "rules_fallback"


def test_capability_ids_are_full_strength(client):
    import re

    unit = _parse_unit(client)
    tpl = _parse_template(client)
    assert re.fullmatch(r"unit_[0-9a-f]{32}", unit["unit_id"])
    assert re.fullmatch(r"tpl_[0-9a-f]{32}", tpl["template_id"])
    r = _generate(client, unit, [unit["lessons"][0]])
    assert re.fullmatch(r"plan_[0-9a-f]{32}", r.get_json()["plan"]["plan_id"])


# ---------------- Multi-lesson (batch) contract ----------------

def test_multi_lesson_returns_plans_and_zip(client):
    unit = _parse_unit(client)
    lessons = unit["lessons"][:2]
    assert len(lessons) == 2
    r = _generate(client, unit, lessons)
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["plans"]) == 2
    assert body["failures"] == []
    import zipfile as zf_

    zf = zf_.ZipFile(io.BytesIO(_b64d(body["zip_b64"])))
    names = zf.namelist()
    assert any(n.endswith(".docx") for n in names)
    for plan in body["plans"]:
        assert plan["docx_b64"]


def test_batch_size_bound(client):
    unit = _parse_unit(client)
    lessons = [unit["lessons"][0]] * 26
    r = _generate(client, unit, lessons)
    assert r.status_code == 400


def test_response_artifact_cap_fails_overflow_lessons_honestly(client, monkeypatch):
    unit = _parse_unit(client)
    lessons = unit["lessons"][:2]
    assert len(lessons) == 2
    # Force the cap below one plan's artifact size: both lessons must fail
    # with the cap reason, no artifacts are returned, and the response is 422.
    monkeypatch.setattr(fa, "MAX_RESPONSE_ARTIFACT_BYTES", 1)
    r = _generate(client, unit, lessons)
    assert r.status_code == 422
    body = r.get_json()
    assert len(body["failures"]) == 2
    assert all("حجم الاستجابة" in f["detail"] or "المهلة الزمنية" in f["detail"] for f in body["failures"])
    assert "plans" not in body and "zip_b64" not in body


def test_response_artifact_cap_keeps_earlier_lessons(client, monkeypatch):
    unit = _parse_unit(client)
    lessons = unit["lessons"][:2]
    # Cap fits roughly one plan: first succeeds, second fails with cap reason.
    r0 = _generate(client, unit, lessons[:1])
    assert r0.status_code == 200
    one_size = len(_b64d(r0.get_json()["plan"]["docx_b64"])) + len(
        _b64d(r0.get_json()["plan"]["pdf_b64"] or b"")
    )
    monkeypatch.setattr(fa, "MAX_RESPONSE_ARTIFACT_BYTES", one_size + 512)
    r = _generate(client, unit, lessons)
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["plans"]) == 1
    assert len(body["failures"]) == 1
    assert "حجم الاستجابة" in body["failures"][0]["detail"]


def test_partial_failure_reports_failures_and_keeps_successes(client):
    unit = _parse_unit(client)
    good = unit["lessons"][0]
    thin_unit = _parse_unit(client, raw=TXT_THIN, name="thin.txt")
    bad = thin_unit["lessons"][0]
    r = _generate(client, unit, [good, bad])
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["plans"]) == 1
    assert len(body["failures"]) == 1
    assert body["failures"][0]["qa_blocked"] is True
    assert body["failures"][0]["blocking_gates"]
    # The failure carries no artifact bytes.
    assert "docx_b64" not in body["failures"][0]


def test_all_failures_return_422(client):
    thin_unit = _parse_unit(client, raw=TXT_THIN, name="thin.txt")
    r = _generate(client, thin_unit, thin_unit["lessons"][:2])
    assert r.status_code == 422
    body = r.get_json()
    assert body["failures"] and "plans" not in body


def test_invalid_lesson_payload_rejected(client):
    unit = _parse_unit(client)
    r = _generate(client, unit, [{"lesson_id": "x"}])
    assert r.status_code == 422


# ---------------- Boundary edit (pure, request-scoped) ----------------

def test_rebind_is_pure_and_stateless(client):
    unit = _parse_unit(client)
    lessons = unit["lessons"]
    edit = [
        {
            "lesson_id": lessons[0]["lesson_id"],
            "title": "عنوان معدل",
            "start_page": lessons[0]["start_page"],
            "end_page": lessons[0]["end_page"],
            "approved": True,
        }
    ]
    r = client.post(
        "/api/curriculum/rebind", json={"unit": unit, "lessons": edit}, headers=HEADERS
    )
    assert r.status_code == 200
    updated = r.get_json()
    assert updated["lessons"][0]["title"] == "عنوان معدل"
    assert updated["lessons"][0]["raw_text"]  # re-sliced from supplied pages
    # Repeating with the original unit yields the same result: nothing stored.
    r2 = client.post(
        "/api/curriculum/rebind", json={"unit": unit, "lessons": edit}, headers=HEADERS
    )
    assert r2.get_json()["lessons"][0]["title"] == "عنوان معدل"


# ---------------- Upload validation (unchanged guards) ----------------

def test_upload_size_bound(client, monkeypatch):
    monkeypatch.setitem(fa.application.config, "MAX_CONTENT_LENGTH", 1024)
    big = b"x" * 2048
    r = client.post(
        "/api/curriculum/parse",
        data={"file": (io.BytesIO(big), "big.txt")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 413


def test_upload_extension_allowlist(client):
    r = client.post(
        "/api/curriculum/parse",
        data={"file": (io.BytesIO(b"MZ..."), "evil.exe")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


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
        "/api/template/parse",
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
        "/api/template/parse",
        data={"docx": (io.BytesIO(xxe), "t.docx")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_utf16_entity_rejected(client):
    payload = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r/>'.encode("utf-16-le")
    xxe = _make_zip([("word/document.xml", payload)])
    r = client.post(
        "/api/template/parse",
        data={"docx": (io.BytesIO(xxe), "t.docx")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_small_entry_ratio_rejected(client):
    bomb = _make_zip([("word/document.xml", b"0" * (2 * 1024 * 1024))])
    r = client.post(
        "/api/template/parse",
        data={"docx": (io.BytesIO(bomb), "t.docx")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_oversized_xml_part_rejected(client):
    big_xml = _make_zip([("word/document.xml", b"<r>" + b"a" * (9 * 1024 * 1024) + b"</r>")])
    r = client.post(
        "/api/template/parse",
        data={"docx": (io.BytesIO(big_xml), "t.docx")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_pdf_page_bound(client):
    import fitz

    doc = fitz.open()
    for _ in range(301):
        doc.new_page()
    data = doc.tobytes()
    r = client.post(
        "/api/curriculum/parse",
        data={"file": (io.BytesIO(data), "big.pdf")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_pdf_page_geometry_bound(client):
    import fitz

    doc = fitz.open()
    doc.new_page(width=4000, height=4000)
    data = doc.tobytes()
    r = client.post(
        "/api/curriculum/parse",
        data={"file": (io.BytesIO(data), "huge.pdf")},
        content_type="multipart/form-data",
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_generation_readiness_reports_rules_without_credentials(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ENABLE_AI_GENERATION", raising=False)
    data = client.get("/api/health").get_json()
    assert data["generation"] == {"mode": "rules_fallback", "ai_enabled": False}
    assert "OPENAI_API_KEY" not in str(data)


def test_generation_readiness_requires_explicit_enable(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-used")
    monkeypatch.delenv("ENABLE_AI_GENERATION", raising=False)
    assert client.get("/api/health").get_json()["generation"]["ai_enabled"] is False
    monkeypatch.setenv("ENABLE_AI_GENERATION", "1")
    assert client.get("/api/health").get_json()["generation"]["mode"] == "ai"


def test_rules_fallback_activities_refer_to_uploaded_python_lesson(client):
    unit = _parse_unit(client)
    from app.engines.rules_engine import build_rules_lesson_plan
    from app.models.schemas import CurriculumUnit, LessonBoundary, GenerationContext, TemplateSchema
    parsed_unit = CurriculumUnit(**unit)
    lesson = parsed_unit.lessons[0]
    schema_data = _parse_template(client)
    schema = TemplateSchema(**schema_data)
    context = GenerationContext(
        unit_id=parsed_unit.unit_id, lesson_id=lesson.lesson_id, template_id=schema.template_id,
        school_name="مدرسة ابدأ", teacher_name="معلم اختبار",
        job_title="معلم", program_or_course="Python",
        grade_level="الصف الأول", academic_year="2026-2027",
        branch="AI", total_duration_minutes=50,
    )
    plan = build_rules_lesson_plan(parsed_unit, lesson, schema, context)
    source = lesson.raw_text
    assert any(term in plan.activity_1.teacher_procedures for term in ("المتغير", "البيانات", "يختار"))
    assert "مقتطف المنهج" in plan.activity_1.teacher_procedures
    assert "سؤال:" in plan.assessment_group_1
    assert plan.assessment_group_1 != "ملاحظة أداء الطلاب أثناء نشاط الدرس"
    assert sum(e.duration_minutes for e in plan.lesson_elements) == 50
    assert plan.teacher_name == "معلم اختبار"
    assert len(source) > 30
