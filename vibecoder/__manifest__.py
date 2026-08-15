# -*- coding: utf-8 -*-
{
    'name': "Vibecoder",
    'summary': "Vibecoder — a Base44/Bolt-style AI coding platform: chat with Claude "
               "to build a web app, backed by your own GitHub repo.",
    'description': """
Vibecoder
=========
A self-contained public website (not built on the `website`/`portal` apps) where a
visitor signs up with an email/password (stored on `res.partner`, no `res.users`
account is ever created), connects their GitHub account, and creates projects.

Each project is a GitHub repository, scaffolded from a bundled Vite/React starter.
A chat panel lets the visitor talk to a headless Claude Code CLI run scoped to that
project's own git checkout — Claude edits real files, commits them, and the running
`npm run dev` preview (reverse-proxied through this same Odoo instance) is refreshed.

Chat responses stream to the browser over genuine Server-Sent Events. File uploads
are chunked. All outbound GitHub calls use exponential back-off retries. Passwords
are hashed with the same pbkdf2_sha512 scheme Odoo itself uses for res.users.
""",
    'author': "CICDoo",
    'website': "https://cicdoo.com",
    'category': 'Productivity/AI',
    'version': '19.0.1.0.0',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'external_dependencies': {'python': ['requests', 'cryptography', 'passlib']},
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'application': True,
    'installable': True,
}
