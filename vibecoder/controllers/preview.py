# -*- coding: utf-8 -*-
import logging

import requests

from odoo import http
from odoo.http import request, Response

from ._helpers import current_vibecoder_partner

_logger = logging.getLogger(__name__)

HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
    "content-encoding", "content-length",
}

STARTING_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Starting preview…</title>
<meta http-equiv="refresh" content="2">
<style>body{font:14px -apple-system,sans-serif;color:#666;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}</style>
</head><body>Starting your preview… this page will refresh automatically.</body></html>"""


class VibecoderPreview(http.Controller):

    def _own_project(self, project_id):
        partner = current_vibecoder_partner()
        project = request.env["vibecoder.project"].sudo().browse(int(project_id))
        if not partner or not project.exists() or project.partner_id.id != partner.id:
            return None
        return project

    @http.route(
        ["/vibecoder/preview/<int:project_id>/",
         "/vibecoder/preview/<int:project_id>/<path:subpath>"],
        type="http", auth="public", csrf=False,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    def preview(self, project_id, subpath="", **kw):
        project = self._own_project(project_id)
        if project is None:
            return request.make_response("Not found.", status=404)
        if not project.preview_pid or not project.preview_port:
            return request.make_response(
                STARTING_PAGE, headers=[("Content-Type", "text/html")], status=503)

        project.touch_preview_activity()

        # The dev server's `base` (see project.action_start_preview) is set to
        # this same "/vibecoder/preview/<id>/" prefix, so the upstream request
        # path must include it too — forward the full incoming path, not just
        # the part after the prefix.
        target = "http://127.0.0.1:%s%s" % (project.preview_port, request.httprequest.path)
        qs = request.httprequest.query_string.decode()
        if qs:
            target += "?" + qs

        fwd_headers = {
            k: v for k, v in request.httprequest.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS and k.lower() != "host"
        }
        try:
            upstream = requests.request(
                request.httprequest.method, target, headers=fwd_headers,
                data=request.httprequest.get_data(), stream=True, timeout=30)
        except requests.RequestException:
            return request.make_response(
                STARTING_PAGE, headers=[("Content-Type", "text/html")], status=503)

        resp_headers = [
            (k, v) for k, v in upstream.raw.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS
        ]
        return Response(
            upstream.iter_content(chunk_size=8192),
            status=upstream.status_code, headers=resp_headers,
            direct_passthrough=True)
