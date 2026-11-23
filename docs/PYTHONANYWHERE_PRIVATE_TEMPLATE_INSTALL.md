# Installing the school-approved default Word/PDF templates

The new default is a compact four-page form (school metadata, outcomes, activities, detailed evaluation).\nThe public GitHub repository must NOT contain original named teacher documents.
Prepare a redacted blank form (DOCX) and a corresponding reference PDF, then
install them in a **private directory on the PythonAnywhere server**.

The Flask application now auto-discovers these files under the home directory:

```text
~/ebda_private_assets/EBDA_Compact_Template_2026-2027.docx
~/ebda_private_assets/EBDA_Compact_Reference_2026-2027.pdf
```

An authorized PythonAnywhere administrator must:
1. Update the PythonAnywhere backend working copy to a commit containing this change.
2. Create `~/ebda_private_assets` and upload the approved DOCX/PDF with the names above.
3. Keep the folder outside `public_html` and outside the GitHub working tree.
4. Reload the PythonAnywhere web app.
5. Open `/api/health`; require `defaults.template === true` and
   `defaults.reference_pdf === true`. Then test `POST /api/template/parse`
   without uploading template files.
6. Test a genuine sample curriculum -> plan -> Word/PDF against the school forms.

Optionally override the default paths with the existing
`EBDA_DEFAULT_TEMPLATE_PATH` and `EBDA_DEFAULT_REFERENCE_PDF_PATH`
environment variables.

**Important:** GitHub Pages deployment updates only the frontend. It cannot
write files to PythonAnywhere or reload its application.
If a teacher saved the templates in their own browser, that remains a
per-browser fallback; it is not centrally installed.
