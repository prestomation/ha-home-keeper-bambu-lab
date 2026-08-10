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
translation string**, except for the handful listed in :data:`_ALLOWED_PLACEHOLDERS` —
the per-printer maintenance steps, which name the printer they're about and are shown
with a matching ``async_show_form(..., description_placeholders=...)``. Each allowlist
entry pins the exact token set, so a typo'd or newly added ``{token}`` still fails.
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

# The only strings allowed to carry ICU placeholders, and the exact set each may use.
# Every one of these is a step description that ``config_flow`` renders with a matching
# ``description_placeholders``; the per-printer maintenance steps have to name the
# printer they're about, which is the whole reason for the exception. Adding an entry
# here means committing to passing those placeholders on every path that shows the step.
_ALLOWED_PLACEHOLDERS: dict[str, set[str]] = {
    ".options.step.model.description": {"printer_name", "detected"},
    ".options.step.items.description": {"printer_name", "model"},
}


def _placeholders(value: str) -> set[str]:
    """The ``{token}`` names in *value*, or ``{"<malformed>"}`` if the braces don't pair."""
    names: set[str] = set()
    rest = value
    while "{" in rest:
        _, _, after = rest.partition("{")
        name, sep, rest = after.partition("}")
        if not sep or "{" in name:
            return {"<malformed>"}
        names.add(name)
    return {"<malformed>"} if "}" in rest else names


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
            if "{" not in value and "}" not in value:
                continue
            allowed = _ALLOWED_PLACEHOLDERS.get(json_path)
            if allowed is not None and _placeholders(value) <= allowed:
                continue
            offenders.append(f"{file.name}{json_path}: {value!r}")
    assert not offenders, (
        "translation strings must not contain '{' or '}' — the frontend parses them as "
        "ICU placeholders and errors when they aren't provided (see this file's docstring). "
        "Reword without braces, or pass description_placeholders and add the string to "
        "_ALLOWED_PLACEHOLDERS. Offenders:\n  " + "\n  ".join(offenders)
    )


def test_every_allowed_placeholder_string_exists():
    """The allowlist must not outlive the strings it excuses."""
    data = json.loads((_COMPONENT_DIR / "strings.json").read_text(encoding="utf-8"))
    present = {path for path, _ in _iter_strings(data)}
    missing = sorted(set(_ALLOWED_PLACEHOLDERS) - present)
    assert not missing, (
        "_ALLOWED_PLACEHOLDERS names strings that no longer exist; drop them so the "
        "exception can't silently cover a future string at the same path: "
        + str(missing)
    )
