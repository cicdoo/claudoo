# Contributing to Claudoo

Thanks for your interest in improving Claudoo! Contributions of all kinds are
welcome — bug reports, documentation, tests, and code.

## Getting started

1. **Fork** the repository and clone your fork.
2. Add the addon to your Odoo `addons_path` (the repo *is* the module folder,
   so point the path at its parent directory).
3. Install with tests enabled on a throwaway database:
   ```bash
   odoo-bin -c odoo.conf -d claudoo_dev -i claudoo --test-enable --stop-after-init
   ```
4. Run the live server and try the **Claudoo** menu.

## Development guidelines

- **Target Odoo 18.0.** Match the surrounding code style (PEP 8, 4-space indent,
  `# -*- coding: utf-8 -*-` headers).
- **Security first.** Claudoo's whole value is its safety model. Any change that
  touches the tool endpoints, the SQL guard, the bridge token, or the auth method
  must keep the invariants in [`SECURITY.md`](SECURITY.md) and ship with tests.
- **Never run tools as superuser.** ORM tool endpoints must act as the user.
- **Keep the engine references intact.** Claudoo wraps the Claude Code CLI; do not
  rename Claude/Anthropic OAuth constants, `CLAUDE_CONFIG_DIR`, the CLI binary
  glob, or fields that store real Claude artifacts (`claude_session_id`,
  `claude_msg_id`).
- **Add tests** under `tests/` for any behavior change. Tests are tagged `claudoo`:
  ```bash
  odoo-bin ... -i claudoo --test-tags claudoo --stop-after-init
  ```

## Pull requests

- One logical change per PR; write a clear description and link any issue.
- Make sure CI is green (lint + tests).
- Update `CHANGELOG.md` under an *Unreleased* heading.
- By contributing, you agree your contributions are licensed under **LGPL-3.0**.

## Commercial support

Claudoo is maintained by [CICDoo](https://cicdoo.com). For managed hosting,
custom tool development, an SLA, or a commercial license, see the *Commercial*
section of the [README](README.md) or email **hello@cicdoo.com**.
