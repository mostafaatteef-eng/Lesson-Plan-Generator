#!/usr/bin/env python3
"""Install the school-approved private lesson-plan files on the backend host.

Run ONLY on the authorized PythonAnywhere backend server. Never commit template
binary files to this public repository or copy them to a public web directory.
"""
from __future__ import annotations

import argparse
import io
import os
from pathlib import Path
import tempfile
import zipfile

WORD = "EBDA_Compact_Template_2026-2027.docx"
PDF = "EBDA_Compact_Reference_2026-2027.pdf"


def load_and_validate(archive: Path) -> dict[str, bytes]:
    import fitz
    from docx import Document

    with zipfile.ZipFile(archive) as z:
        names = set(z.namelist())
        if not {WORD, PDF}.issubset(names):
            raise ValueError("Archive must contain the exact approved DOCX/PDF filenames.")
        if any(z.getinfo(name).file_size > 15 * 1024 * 1024 for name in (WORD, PDF)):
            raise ValueError("A template file exceeds the 15 MB safety limit.")
        files = {name: z.read(name) for name in (WORD, PDF)}

    document = Document(io.BytesIO(files[WORD]))
    text = "\n".join(
        [p.text for p in document.paragraphs]
        + [cell.text for table in document.tables for row in table.rows for cell in row.cells]
    )
    if "اسم المعلم" not in text:
        raise ValueError("DOCX has no teacher name field on the compact template.")
    with fitz.open(stream=files[PDF], filetype="pdf") as pdf:
        if len(pdf) != 4:
            raise ValueError(f"Expected the 4-page reference PDF, got {len(pdf)} pages.")
        if "اسم المعلم" not in pdf[0].get_text():
            raise ValueError("Reference PDF first page is missing teacher name.")
    return files


def install(archive: Path, directory: Path) -> None:
    files = load_and_validate(archive)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Private asset directory must not be a symlink.")
    os.chmod(directory, 0o700)

    for name, data in files.items():
        path = directory / name
        if path.is_symlink():
            raise ValueError(f"Refusing to overwrite symlink: {path}")
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=directory, prefix=".ebda-", delete=False) as tmp:
                tmp_path = Path(tmp.name)
                tmp.write(data)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, path)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
        print(f"Installed validated private asset: {path}")

    print("Next: reload the PythonAnywhere web application; verify /api/health defaults are true.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path, help="Approved ZIP with DOCX/PDF at its root")
    parser.add_argument("--dest", type=Path, default=Path.home() / "ebda_private_assets")
    args = parser.parse_args()
    install(args.archive.expanduser(), args.dest.expanduser())


if __name__ == "__main__":
    main()
