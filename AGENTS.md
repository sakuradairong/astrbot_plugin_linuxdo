# Repository Instructions

## What this repo is
- AstrBot plugin package named `astrbot_plugin_linuxdo`; install the whole directory under `AstrBot/data/plugins/astrbot_plugin_linuxdo`.
- `main.py` is the AstrBot entrypoint and imports helpers with package-relative imports from `.linuxdo_preview`; tests should import `astrbot_plugin_linuxdo.main`, not top-level `main`.
- `linuxdo_preview/` contains the reusable helper layer: extraction, auth/cookie handling, HTML card rendering, screenshot rendering, sanitizer, and typed topic payloads.
- Runtime data is written under `data/plugin_data/astrbot_plugin_linuxdo/screenshots/` via AstrBot's `get_astrbot_data_path()`.
- Automatic preview is gated by `allowed_group_ids` when configured; private chats are allowed by default, and an empty whitelist preserves all-group behavior.

## Runtime dependencies and setup
- Plugin dependencies are only in `requirements.txt`: `scrapling[fetchers]>=0.4` and `lxml>=5.0`.
- A real AstrBot install also needs Scrapling's browser installed: `pip install scrapling[fetchers] && scrapling install`.
- If Scrapling is missing, `main.py` intentionally still imports but raises/logs `Scrapling 未安装` at runtime paths.
- `_conf_schema.json` is the source of truth for plugin config keys shown in AstrBot WebUI.

## Verification commands
- Run all tests from the repo root with `python3 -m unittest discover -s tests`.
- Run one focused test with `python3 -m unittest tests.test_main_preview.TestMainUrlExtraction.test_imports_as_plugin_package_from_plugins_parent`.
- Syntax-check Python files with `python3 -m py_compile main.py linuxdo_preview/*.py tests/*.py`.
- Validate config schema JSON with `python3 -m json.tool _conf_schema.json >/tmp/opencode/astrbot_plugin_linuxdo_conf_schema.json`.

## Testing quirks
- Tests stub AstrBot modules in `tests/test_main_preview.py`; do not require AstrBot to be installed locally for unit tests.
- The package import regression simulates only the plugins parent directory on `sys.path`; keep it when changing imports.
- Local type/LSP checks may report missing `astrbot`, `scrapling`, or `lxml` if they are not installed in the agent environment; confirm with unit tests and `py_compile` before treating those as repo regressions.

## Behavior and security gotchas
- `linuxdo_session_cookie` may expose restricted linux.do content to the chat where a link is posted; preserve README and `_conf_schema.json` warnings when touching auth/config.
- Do not describe linux.do `_t` as long-lived; users report `_t` can expire quickly, so docs should say cookies may need refreshing.
- For the most stable practical auth, recommend pasting the full `linux.do` request `Cookie` header instead of only one cookie; this may include `_t`, `_forum_session`, `cf_clearance`, and related browser-session cookies, but still can expire.
- `/linuxdo_auth` must never print cookie values; showing cookie names such as `_t` or `_forum_session` is acceptable.
- Do not reintroduce username/password login behavior; linux.do hCaptcha makes it unsupported and docs mark those config keys deprecated.
- HTML from Discourse cooked content must remain sanitized before rendering; sanitizer failures should fail closed rather than send raw cooked HTML.
- `use_api_render` defaults to true and is the preferred path: fetch Discourse JSON, render the custom card, then screenshot it. Page screenshot is fallback behavior.

## Design/card notes
- `DESIGN.md` is the source of truth for the preview card design system.
- Card CSS lives in `linuxdo_preview/card_styles.py` as `PREVIEW_CARD_CSS`; `linuxdo_preview/html_card.py` owns the generated card structure.
- Keep stats labels text-based, not emoji-based, to avoid inconsistent screenshot rendering across Linux browser/font environments.
