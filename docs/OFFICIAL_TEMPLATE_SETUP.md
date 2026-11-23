# School-owned lesson preparation templates

## Teacher workflow (no repeat upload on the same browser)

1. Open the EBDA lesson studio on the device you normally use.
2. Select the official `.docx` preparation form and the approved `.pdf` reference **once**.
3. The files are preserved in that browser's IndexedDB. When you return, they are restored, parsed and reused automatically.
4. On subsequent visits, upload **only the curriculum**. Use the remove action if you wish to forget or replace a saved template.

No curriculum content is persisted in IndexedDB. Clearing browser/site storage, switching to a private window or using another browser/device will require selecting the template again.

## All teachers, all devices: centrally installed official template

The production Flask backend already supports *server-private* default assets. An authorized PythonAnywhere administrator can install the school's approved, scrubbed copies outside the public repository, for example:

```text
/home/<pythonanywhere-user>/ebda_private_assets/official_lesson_plan.docx
/home/<pythonanywhere-user>/ebda_private_assets/official_lesson_plan_reference.pdf
```

Set the server environment variables (exact paths vary by hosting account):

```bash
EBDA_DEFAULT_TEMPLATE_PATH=/home/<pythonanywhere-user>/ebda_private_assets/official_lesson_plan.docx
EBDA_DEFAULT_REFERENCE_PDF_PATH=/home/<pythonanywhere-user>/ebda_private_assets/official_lesson_plan_reference.pdf
```

Restart/reload the PythonAnywhere web application. Check `/api/health`: `defaults.template` and `defaults.reference_pdf` should both be `true`. The frontend then automatically loads the default without teacher intervention.

**Privacy:** Do not commit example teacher names, personal document metadata or editable original templates to a public repo. Review the original examples first; the uploaded samples contain previous-year and named-teacher content. Built-in default files must be school-approved and scrubbed. Do not assume embedding files in GitHub Pages is private.

**Important:** Code deployment to GitHub Pages does not deploy files or environment variables to PythonAnywhere. Treat these as separate release steps.
