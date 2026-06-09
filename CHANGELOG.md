# Changelog

All notable changes to **Claudoo** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
Odoo-style versioning (`18.0.MAJOR.MINOR.PATCH`).

## [18.0.1.0.0] — First public release

First open-source release of Claudoo, an in-Odoo AI assistant that drives the
Claude Code CLI over a sandboxed, permission-aware bridge.

### Features
- **Chat client action** (OWL) with real-time streaming over the Odoo bus.
- **Permission-aware ORM tools** — every action runs as the *current user*
  (never superuser); `ir.model.access` and record rules are always enforced.
- **Read-only SQL reporting** (`sql_select`) gated to the *AI SQL Analyst* group,
  guarded by a SELECT-only text validator plus Postgres `SET TRANSACTION READ ONLY`
  and a statement timeout.
- **Per-user OAuth** ("Login with Claude") — no shared API key; credentials are
  stored privately per user, mode `0600`, never in the database.
- **Hard-denied built-ins** — the model can act *only* through the `mcp__odoo__*`
  tools; Bash/Read/Write/Web/agent-spawners are denied.
- **Immutable audit log** (`claudoo.tool_log`) written on a separate committed
  cursor so it survives rollbacks.
- **Zero-trust mode** (global default + per-user override) that strips all write
  tools.
- **Test suite** covering the SQL guard, bridge-token mint/verify, tool-access
  policy, the `ai_bridge` auth method, and the audit log.

### Licensing
- **Dual-licensed**: open-source **LGPL-3.0-or-later** *or* a **commercial license**
  from CICDoo (see `COMMERCIAL_LICENSE.md`). Every source file carries an SPDX
  `LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial` notice.
- Runs on **both Odoo Community and Enterprise** editions (depends only on
  Community modules: `web`, `bus`, `mail`).

[18.0.1.0.0]: https://github.com/cicdoo/claudoo/releases/tag/18.0.1.0.0
