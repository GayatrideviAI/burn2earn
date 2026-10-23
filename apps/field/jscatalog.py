"""The words the offline phone app needs, for every language, as JSON for its page.

The phone app is plain JavaScript that works with no signal, so it carries its own copy of the
translations. The phrases are the ones written as t("...") in app.js; each is looked up in the
Hindi and Punjabi catalogues. Phrases without a translation are left out, so English shows.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from django.utils import translation
from django.utils.translation import gettext

JS_PHRASE = re.compile(r"""(?<![\w.$])t\(\s*"((?:[^"\\\n]|\\.)*)\"""")


def phrases_in(path):
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads('"' + m.group(1) + '"') for m in JS_PHRASE.finditer(text)]


MITRA_JS = Path(__file__).parent / "static" / "field" / "app.js"
# The photo screens are shared by the Mitra and Yard apps, so both carry their phrases.
PHOTOS_JS = Path(__file__).parent.parent / "weightphotos" / "static" / "weightphotos" / "photos.js"


@lru_cache(maxsize=None)
def _phrases(paths):
    return sorted({p for path in paths for p in phrases_in(path)})


def _as_paths(path):
    return tuple(Path(x) for x in (path if isinstance(path, (list, tuple)) else [path]))


def js_catalog(path=(MITRA_JS, PHOTOS_JS)):
    catalog = {}
    for code in ("hi", "pa"):
        with translation.override(code):
            catalog[code] = {p: gettext(p) for p in _phrases(_as_paths(path)) if gettext(p) != p}
    return catalog


def js_catalog_json(path=(MITRA_JS, PHOTOS_JS)):
    # Safe to place inside a <script> tag.
    text = json.dumps(js_catalog(path), ensure_ascii=False)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
