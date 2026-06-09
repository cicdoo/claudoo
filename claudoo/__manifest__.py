# -*- coding: utf-8 -*-
# Copyright 2026 CICDoo (https://cicdoo.com)
# SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial
# Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
{
    'name': "Claudoo",
    'summary': "Claudoo — chat with your Odoo, safely. A Claude-powered assistant with "
               "permission-aware ORM tools and read-only SQL reporting.",
    'description': """
Claudoo — AI Assistant for Odoo
===============================
A chat interface (menu + OWL client action) that drives the Claude Code CLI headless on
the server. The assistant can query Odoo and build reports through a small set of safe
tools exposed over a sandboxed MCP bridge:

* Every ORM action runs with the **current user's** permission level (never superuser).
* Raw SQL reporting is **read-only** (SELECT only) and gated to the *AI SQL Analyst* group.
* Claude's own built-in tools (Bash, file write, web) are disabled; it can only act
  through the Odoo tool endpoints.
* Replies stream into the chat in real time over the Odoo bus.

Authentication is per-user OAuth (no API key, no shared subscription): each user
clicks **Login with Claude** in the chat, authorizes with their own Claude
subscription, and their credentials are stored privately in a per-user
CLAUDE_CONFIG_DIR. Chatting is gated until the current user has connected.
""",
    'author': "CICDoo",
    'website': "https://cicdoo.com",
    'category': 'Productivity/AI',
    'version': '18.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['web', 'bus', 'mail'],
    'external_dependencies': {'python': ['requests']},
    'data': [
        'security/claudoo_security.xml',
        'security/ir.model.access.csv',
        'data/claudoo_tool_data.xml',
        'data/claudoo_action.xml',
        'views/res_config_settings_views.xml',
        'views/res_users_views.xml',
        'views/claudoo_log_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'claudoo/static/src/scss/claudoo.scss',
            'claudoo/static/src/claudoo_service.js',
            'claudoo/static/src/markdown.js',
            'claudoo/static/src/components/message.js',
            'claudoo/static/src/components/message.xml',
            'claudoo/static/src/components/message_list.js',
            'claudoo/static/src/components/message_list.xml',
            'claudoo/static/src/components/composer.js',
            'claudoo/static/src/components/composer.xml',
            'claudoo/static/src/chat_action.js',
            'claudoo/static/src/chat_action.xml',
        ],
    },
    'application': True,
    'installable': True,
}
