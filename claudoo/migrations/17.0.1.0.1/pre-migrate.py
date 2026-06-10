# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
"""Pre-migration for the res.config.settings / res.users field rename
(ai_* -> claudoo_*) that namespaces Claudoo's fields on the shared models.

Two jobs:

1. Drop the stale inherited res.users views from the previous release whose
   stored arch still references the old ``ai_*`` field names. The data phase
   loads security before views, and writing the security groups regenerates the
   combined res.users "user groups" view — which would validate the obsolete
   field references and abort the upgrade. The views are recreated from the
   current XML later in this same upgrade.

2. Preserve per-user data for the one *stored* renamed field,
   ``ai_zero_trust_mode`` -> ``claudoo_zero_trust_mode``. We copy the values into
   the new (namespaced) column. We do NOT drop the old column: older codexoo
   releases historically shared this exact column on res.users, so an orphan
   column is harmless, whereas dropping it could affect a sibling module.

   ``ai_claude_oauth_set`` is a *computed* (non-stored) field — no column, so
   nothing to migrate there.
"""
import logging

_logger = logging.getLogger(__name__)

# xmlids (module 'claudoo') of the inherited res.users views to drop.
STALE_VIEWS = ("view_users_form_ai_oauth", "view_users_form_simple_ai_oauth")


def migrate(cr, version):
    if not version:
        return  # fresh install: nothing to migrate

    # 1) Remove stale res.users views referencing the pre-rename field names.
    cr.execute("""
        DELETE FROM ir_ui_view WHERE id IN (
            SELECT res_id FROM ir_model_data
            WHERE module = 'claudoo' AND model = 'ir.ui.view' AND name IN %s
        )
    """, (STALE_VIEWS,))
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE module = 'claudoo' AND model = 'ir.ui.view' AND name IN %s
    """, (STALE_VIEWS,))

    # 2) Carry per-user zero-trust selection across the rename.
    cr.execute("""
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'res_users' AND column_name = 'ai_zero_trust_mode'
    """)
    if cr.fetchone():
        cr.execute("""
            ALTER TABLE res_users
            ADD COLUMN IF NOT EXISTS claudoo_zero_trust_mode VARCHAR
        """)
        cr.execute("""
            UPDATE res_users
            SET claudoo_zero_trust_mode = COALESCE(ai_zero_trust_mode, 'inherit')
            WHERE claudoo_zero_trust_mode IS NULL
        """)
        _logger.info(
            "claudoo pre-migration: copied ai_zero_trust_mode -> "
            "claudoo_zero_trust_mode (%s rows)", cr.rowcount)

    _logger.info(
        "claudoo pre-migration: removed stale res.users views %s", STALE_VIEWS)
