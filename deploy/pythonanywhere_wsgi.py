# WSGI config for mostafaatteef.pythonanywhere.com
# EBDA AI Lesson Studio - Flask backend (native WSGI)
import site
import sys

PROJECT_HOME = "/home/mostafaatteef/ebda-lesson-studio"
VENV_SITE_PACKAGES = PROJECT_HOME + "/.venv/lib/python3.13/site-packages"

site.addsitedir(VENV_SITE_PACKAGES)
if PROJECT_HOME not in sys.path:
    sys.path.insert(0, PROJECT_HOME)

from app.flask_app import application  # noqa: E402
