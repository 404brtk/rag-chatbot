import re

LANG_CODE_RE = re.compile(r"^[a-z]{2}(-[a-z]{2,3})?$")
ENGLISH_FOLDERS = ("en", "en-us", "en-gb")


def is_lang_code(segment: str) -> bool:
    return bool(LANG_CODE_RE.match(segment))
