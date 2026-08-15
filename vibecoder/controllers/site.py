# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

from ._helpers import current_vibecoder_partner

BASE_HEAD = """<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="/vibecoder/static/src/css/vibecoder.css">
<script src="/vibecoder/static/src/js/rpc.js"></script>"""


def _page(title, body, extra_head=""):
    return """<!DOCTYPE html><html><head><title>%s · Vibecoder</title>%s%s</head>
<body>%s</body></html>""" % (title, BASE_HEAD, extra_head, body)


def _topbar(partner):
    if partner:
        right = (
            '<div style="display:flex;gap:14px;align-items:center">'
            '<span style="color:var(--vc-muted);font-size:13px">%s</span>'
            '<a href="/vibecoder/github/connect">GitHub%s</a>'
            '<a href="#" onclick="vcRpc(\'/vibecoder/auth/logout\',{}).then('
            "()=>location.href='/vibecoder/login')\">Logout</a></div>"
        ) % (
            partner.name,
            " ✓" if request.env["vibecoder.github_account"].sudo().search_count(
                [("partner_id", "=", partner.id)]) else "",
        )
    else:
        right = '<a href="/vibecoder/login">Log in</a>'
    return (
        '<div class="vc-topbar"><a href="/vibecoder">⚡ Vibecoder</a>%s</div>' % right)


class VibecoderSite(http.Controller):

    @http.route("/vibecoder", type="http", auth="public", csrf=False)
    def dashboard(self, **kw):
        partner = current_vibecoder_partner()
        if not partner:
            return request.redirect("/vibecoder/login")
        body = """
        %s
        <div class="vc-container">
            <div class="vc-card">
                <form id="vc-new-project-form">
                    <label for="vc-project-name">New project name</label>
                    <input id="vc-project-name" name="name" placeholder="my-app" required>
                    <button type="submit">Create project</button>
                </form>
                <div class="vc-error" id="vc-error"></div>
            </div>
            <div class="vc-project-list" id="vc-project-list">Loading…</div>
        </div>
        <script src="/vibecoder/static/src/js/dashboard.js"></script>
        """ % _topbar(partner)
        return request.make_response(_page("Dashboard", body), headers=[("Content-Type", "text/html")])

    @http.route("/vibecoder/login", type="http", auth="public", csrf=False)
    def login_page(self, **kw):
        if current_vibecoder_partner():
            return request.redirect("/vibecoder")
        body = """
        %s
        <div class="vc-container">
            <div class="vc-card vc-form">
                <h2>Log in</h2>
                <form id="vc-login-form">
                    <label>Email</label>
                    <input type="email" name="login" required>
                    <label>Password</label>
                    <input type="password" name="password" required>
                    <button type="submit">Log in</button>
                </form>
                <div class="vc-error" id="vc-error"></div>
                <p style="margin-top:16px;color:var(--vc-muted)">
                    No account? <a href="/vibecoder/signup">Sign up</a>
                </p>
            </div>
        </div>
        <script src="/vibecoder/static/src/js/auth.js"></script>
        <script>vcInitAuthForm("vc-login-form", "/vibecoder/auth/login", "/vibecoder");</script>
        """ % _topbar(None)
        return request.make_response(_page("Log in", body), headers=[("Content-Type", "text/html")])

    @http.route("/vibecoder/signup", type="http", auth="public", csrf=False)
    def signup_page(self, **kw):
        if current_vibecoder_partner():
            return request.redirect("/vibecoder")
        body = """
        %s
        <div class="vc-container">
            <div class="vc-card vc-form">
                <h2>Create your account</h2>
                <form id="vc-signup-form">
                    <label>Name</label>
                    <input type="text" name="name" required>
                    <label>Email</label>
                    <input type="email" name="login" required>
                    <label>Password</label>
                    <input type="password" name="password" minlength="8" required>
                    <button type="submit">Sign up</button>
                </form>
                <div class="vc-error" id="vc-error"></div>
                <p style="margin-top:16px;color:var(--vc-muted)">
                    Already have an account? <a href="/vibecoder/login">Log in</a>
                </p>
            </div>
        </div>
        <script src="/vibecoder/static/src/js/auth.js"></script>
        <script>vcInitAuthForm("vc-signup-form", "/vibecoder/auth/signup", "/vibecoder");</script>
        """ % _topbar(None)
        return request.make_response(_page("Sign up", body), headers=[("Content-Type", "text/html")])

    @http.route("/vibecoder/project/<int:project_id>", type="http", auth="public", csrf=False)
    def project_workspace(self, project_id, **kw):
        partner = current_vibecoder_partner()
        if not partner:
            return request.redirect("/vibecoder/login")
        project = request.env["vibecoder.project"].sudo().browse(project_id)
        if not project.exists() or project.partner_id.id != partner.id:
            return request.make_response("Not found.", status=404)

        claude_connected = partner._vibecoder_ai_is_authenticated()
        claude_banner = "" if claude_connected else (
            '<div class="vc-card" style="border-color:var(--vc-accent)">'
            'Connect your Claude account to start chatting. '
            '<a href="#" onclick="vcConnectClaude()">Connect Claude</a>'
            '<div class="vc-error" id="vc-claude-error" style="display:none"></div>'
            '<div id="vc-claude-code-box" style="display:none;margin-top:10px">'
            '<input id="vc-claude-code-input" placeholder="Paste the code#state here">'
            '<button onclick="vcCompleteClaude()">Confirm</button></div>'
            '</div>'
        )
        body = """
        %s
        <div class="vc-container" style="max-width:100%%;padding:16px">
            %s
        </div>
        <div class="vc-workspace">
            <div class="vc-chat-pane">
                <div class="vc-messages" id="vc-messages"></div>
                <form class="vc-composer" id="vc-composer-form">
                    <textarea id="vc-composer-input" placeholder="Ask Claude to build something…"></textarea>
                    <button id="vc-send-btn" style="width:auto" %s>Send</button>
                </form>
                <div class="vc-error" id="vc-error" style="margin:0 12px 12px"></div>
            </div>
            <div class="vc-preview-pane">
                <div class="vc-preview-toolbar">
                    <span class="vc-badge" id="vc-project-state">–</span>
                    <button id="vc-start-btn" style="width:auto;display:none">Start preview</button>
                </div>
                <iframe id="vc-preview-frame"></iframe>
            </div>
        </div>
        <script src="/vibecoder/static/src/js/workspace.js"></script>
        <script>
            vcInitWorkspace(%s);
            async function vcConnectClaude() {
                try {
                    const { url } = await vcRpc("/vibecoder/claude/start", {});
                    window.open(url, "_blank");
                    document.getElementById("vc-claude-code-box").style.display = "block";
                } catch (e) { vcShowError(document.getElementById("vc-claude-error"), e); }
            }
            async function vcCompleteClaude() {
                const code = document.getElementById("vc-claude-code-input").value.trim();
                try {
                    await vcRpc("/vibecoder/claude/complete", { code });
                    location.reload();
                } catch (e) { vcShowError(document.getElementById("vc-claude-error"), e); }
            }
        </script>
        """ % (
            _topbar(partner), claude_banner,
            "" if claude_connected else "disabled", project.id,
        )
        return request.make_response(
            _page(project.name, body), headers=[("Content-Type", "text/html")])
