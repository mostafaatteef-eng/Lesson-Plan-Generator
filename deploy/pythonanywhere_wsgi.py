# -*- coding: utf-8 -*-
"""PythonAnywhere WSGI entry point for EBDA AI Lesson Studio (Flask native).

Maps the web app to the Flask application and loads optional KEY=VALUE
environment lines (e.g. APP_PASSCODE) from ~/.config/lesson_studio_env.
"""
import os
import site
import sys

BASE = "/home/mostafaatteef/ebda-lesson-studio"
site.addsitedir(BASE + "/.venv311/lib/python3.11/site-packages")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

_env_file = os.path.expanduser("~/.config/lesson_studio_env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as _fh:
        for _line in _fh:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

from app.flask_app import application  # noqa: E402
