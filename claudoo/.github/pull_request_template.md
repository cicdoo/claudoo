## What does this PR do?

<!-- A short summary of the change and the motivation. Link any issue: Closes #123 -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactor / chore

## Checklist

- [ ] Targets Odoo 18.0 and follows the existing code style
- [ ] Added/updated tests under `tests/` (tagged `claudoo`); CI is green
- [ ] Updated `CHANGELOG.md`
- [ ] Tool endpoints still run **as the user, never superuser**
- [ ] Did not alter Claude/Anthropic engine references (OAuth, `CLAUDE_CONFIG_DIR`,
      CLI glob, `claude_session_id` / `claude_msg_id`)
- [ ] For security-sensitive changes: invariants in `SECURITY.md` are preserved
