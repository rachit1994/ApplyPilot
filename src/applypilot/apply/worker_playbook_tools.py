"""Tool alias preamble: playbook verb names → Playwright MCP tools."""

from __future__ import annotations

from applypilot.apply.prompt_scripts import FORM_VERIFY_JS


def build_tool_alias_section() -> str:
    """Map playbook tool verbs to the MCP tools the runtime exposes."""
    return f"""---

## TOOLS (only these calls are allowed)

| Playbook verb | MCP tool | Usage |
|---|---|---|
| `navigate` | `browser_navigate` | Open the job application URL |
| `verify_page_state` | `browser_evaluate` | Run the form verification script (see below) |
| `fill_form` | `browser_fill_form` | At most 5 fields per call |
| `file_upload` | `browser_file_upload` | Upload `{{resume_pdf_path}}` |
| `click` | `browser_click` | Apply / Submit / option buttons |

### verify_page_state

Call `browser_evaluate` with this function body (returns JSON):

```javascript
{FORM_VERIFY_JS}
```

Read `emptyRequired` (count of empty required fields) and `visibleErrors` (array of error strings) from the result. Use the `fields` list for FIELD MAP matching (each item has `label`, `value`, `empty`).

"""

