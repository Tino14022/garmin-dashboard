"""Assembly of the final HTML page from the two templates plus the payload."""
from __future__ import annotations

import json
from pathlib import Path


def extract_running_tab(running_html: str) -> tuple[str, str, str]:
    """Split the standalone running template into (style, body, script)."""
    style_start = running_html.index("<style>") + len("<style>")
    style_end = running_html.index("</style>", style_start)
    style_content = running_html[style_start:style_end]

    body_start = running_html.index("<body>") + len("<body>")
    body_end = running_html.index("<script>")
    script_start = body_end + len("<script>")
    script_end = running_html.index("</script>", script_start)

    body_content = running_html[body_start:body_end]
    script_content = running_html[script_start:script_end]

    # DATA is declared once by the app shell; strip the running template's own
    # declaration and its footer line (the shell owns the shared footer).
    script_content = script_content.replace("const DATA = __DASHBOARD_DATA__;", "")
    script_content = "\n".join(
        line for line in script_content.splitlines() if "el('footer')" not in line
    )
    body_content = body_content.replace('<footer id="footer"></footer>', "")
    return style_content, body_content, script_content


def build_html(data: dict, *, app_template: Path, running_template: Path) -> str:
    payload = json.dumps(data, default=str)
    style_content, body_content, script_content = extract_running_tab(
        Path(running_template).read_text(encoding="utf-8")
    )
    app_html = Path(app_template).read_text(encoding="utf-8")
    # Injected before the shell's own <style> block so the shell's rules win
    # the cascade for any class name both files happen to define.
    app_html = app_html.replace("__RUNNING_TAB_STYLE__", style_content)
    app_html = app_html.replace("__RUNNING_TAB_CONTENT__", body_content)
    app_html = app_html.replace("__RUNNING_TAB_SCRIPT__", script_content)
    app_html = app_html.replace("__DASHBOARD_DATA__", payload)
    return app_html
