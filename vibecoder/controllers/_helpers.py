# -*- coding: utf-8 -*-
import json

from odoo.http import request

SESSION_KEY = "vibecoder_partner_id"


def current_vibecoder_partner():
    """Resolve the logged-in Vibecoder partner from the signed server-side
    session, re-checking existence/active status on every call — never trust
    a value cached earlier in the request."""
    partner_id = request.session.get(SESSION_KEY)
    if not partner_id:
        return None
    partner = request.env["res.partner"].sudo().browse(partner_id)
    if not partner.exists() or not partner.vibecoder_active or not partner.vibecoder_login:
        return None
    return partner


def login_partner(partner):
    from odoo.http import root
    # Session-fixation hardening: rotate the session id on privilege change,
    # same as Odoo core does on a normal login. Our partner never sets
    # session.uid (there is no res.users here), so this only changes the sid
    # and never touches the uid-based session_token.
    root.session_store.rotate(request.session, request.env)
    request.session[SESSION_KEY] = partner.id


def logout_partner():
    request.session.pop(SESSION_KEY, None)


def json_response(data, status=200):
    return request.make_response(
        json.dumps(data), headers=[("Content-Type", "application/json")], status=status)


def json_error(message, status=400):
    return json_response({"error": message}, status=status)


def client_ip():
    return request.httprequest.headers.get("X-Forwarded-For", request.httprequest.remote_addr) or ""
