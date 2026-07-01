"""Guard against config/options-flow translation placeholder bugs.

The Home Assistant frontend renders config- and options-flow strings through
``formatjs`` (ICU MessageFormat), which treats ``{token}`` as a **variable** to
substitute. This glue never passes ``description_placeholders``, so *any* ``{`` / ``}``
in a translation string is a bug that surfaces two ways we learned the hard way:

* a plain ``{printer_name}`` passes ``hassfest`` (it's a valid placeholder identifier)
  but throws ``formatjs … MISSING_VALUE`` at runtime when the options dialog opens; and
* ICU-escaping it (``'{'printer_name'}'``) instead fails ``hassfest``
  ("placeholders must be valid identifiers").

Neither is caught by the panel e2e tier (it never opens the integration's options
dialog), so this cheap static check is the backstop: **no literal braces in any
translation string.** If a future string genuinely needs a placeholder, provide it via
``async_show_form(..., description_placeholders=...)`` and narrow this test accordingly.
"""

from __future__ import annotations

import json
from pathlib import Path

_COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "custom_components"
    / "home_keeper_bambu_lab"
)

_TRANSLATION_FILES = [
    _COMPONENT_DIR / "strings.json",
    *sorted((_COMPONENT_DIR / "translations").glob("*.json")),
]


def _iter_strings(node, path=""):
    """Yield every ``(json_path, value)`` leaf string in *node*."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _iter_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _iter_strings(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def test_translation_files_have_no_placeholder_braces():
    assert _TRANSLATION_FILES, "no translation files found"
    offenders: list[str] = []
    for file in _TRANSLATION_FILES:
        data = json.loads(file.read_text(encoding="utf-8"))
        for json_path, value in _iter_strings(data):
            if "{" in value or "}" in value:
                offenders.append(f"{file.name}{json_path}: {value!r}")
    assert not offenders, (
        "translation strings must not contain '{' or '}' — the frontend parses them as "
        "ICU placeholders and errors when they aren't provided (see this file's docstring). "
        "Reword without braces, or pass description_placeholders. Offenders:\n  "
        + "\n  ".join(offenders)
    )
