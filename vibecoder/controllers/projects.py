# -*- coding: utf-8 -*-
from odoo import http
from odoo.exceptions import UserError
from odoo.http import request

from ._helpers import current_vibecoder_partner


class VibecoderProjects(http.Controller):

    def _require_partner(self):
        partner = current_vibecoder_partner()
        if not partner:
            raise UserError("Please log in first.")
        return partner

    def _own_project(self, project_id, partner):
        project = request.env["vibecoder.project"].sudo().browse(int(project_id))
        # Ownership is enforced here in the controller layer (there is no
        # res.users-based ir.rule for anonymous site visitors).
        if not project.exists() or project.partner_id.id != partner.id:
            raise UserError("Project not found.")
        return project

    @http.route("/vibecoder/projects", type="jsonrpc", auth="public", csrf=False)
    def list_projects(self):
        partner = self._require_partner()
        projects = request.env["vibecoder.project"].sudo().search(
            [("partner_id", "=", partner.id)])
        return {"projects": [_project_dict(p) for p in projects]}

    @http.route("/vibecoder/projects/create", type="jsonrpc", auth="public", csrf=False)
    def create_project(self, name=None):
        partner = self._require_partner()
        name = (name or "").strip()
        if not name:
            raise UserError("Please give your project a name.")
        project = request.env["vibecoder.project"].sudo().create({
            "partner_id": partner.id, "name": name,
        })
        project.action_create_project()
        return {"project": _project_dict(project)}

    @http.route("/vibecoder/projects/<int:project_id>", type="jsonrpc", auth="public", csrf=False)
    def get_project(self, project_id):
        partner = self._require_partner()
        project = self._own_project(project_id, partner)
        return {"project": _project_dict(project)}

    @http.route("/vibecoder/projects/<int:project_id>/start", type="jsonrpc", auth="public", csrf=False)
    def start_preview(self, project_id):
        partner = self._require_partner()
        project = self._own_project(project_id, partner)
        project.action_start_preview()
        return {"project": _project_dict(project)}

    @http.route("/vibecoder/projects/<int:project_id>/stop", type="jsonrpc", auth="public", csrf=False)
    def stop_preview(self, project_id):
        partner = self._require_partner()
        project = self._own_project(project_id, partner)
        project.action_stop_preview()
        return {"project": _project_dict(project)}


def _project_dict(project):
    return {
        "id": project.id,
        "name": project.name,
        "state": project.state,
        "last_error": project.last_error,
        "github_repo_full_name": project.github_repo_full_name,
        "preview_running": bool(project.preview_pid),
        "preview_url": "/vibecoder/preview/%s/" % project.id if project.preview_pid else None,
    }
