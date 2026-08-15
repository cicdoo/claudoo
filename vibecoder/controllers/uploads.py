# -*- coding: utf-8 -*-
import json
import math
import os
import re
import time
import uuid

from odoo import http
from odoo.http import request

from ._helpers import current_vibecoder_partner, json_error, json_response

ALLOWED_UPLOAD_EXTS = {
    ".txt", ".csv", ".tsv", ".json", ".xml", ".md", ".markdown", ".rst",
    ".log", ".yaml", ".yml", ".ini", ".conf", ".cfg", ".toml", ".env",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".htm", ".css", ".scss",
    ".sql", ".sh", ".c", ".h", ".cpp", ".hpp", ".java", ".go", ".rb", ".php",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".zip",
}
DEFAULT_MAX_MB = 50
DEFAULT_CHUNK_MB = 4
UPLOADS_SUBDIR = ".uploads"


class VibecoderUploads(http.Controller):

    def _config(self, key, default):
        val = request.env["ir.config_parameter"].sudo().get_param("vibecoder.%s" % key)
        return int(val) if val else default

    def _own_project(self, project_id):
        partner = current_vibecoder_partner()
        if not partner:
            return None, None
        project = request.env["vibecoder.project"].sudo().browse(int(project_id))
        if not project.exists() or project.partner_id.id != partner.id:
            return None, None
        return partner, project

    def _uploads_root(self, project):
        path = os.path.join(project._get_local_path(), UPLOADS_SUBDIR)
        os.makedirs(path, mode=0o700, exist_ok=True)
        return path

    def _safe_dest_path(self, project, dest_path):
        """Resolve dest_path relative to the project tree; reject traversal."""
        local_root = os.path.realpath(project._get_local_path())
        candidate = os.path.realpath(os.path.join(local_root, dest_path.lstrip("/")))
        if candidate != local_root and not candidate.startswith(local_root + os.sep):
            return None
        return candidate

    @http.route("/vibecoder/project/<int:project_id>/upload/init",
                type="http", auth="public", csrf=False, methods=["POST"])
    def upload_init(self, project_id, **kw):
        _partner, project = self._own_project(project_id)
        if not project:
            return json_error("Project not found.", status=404)

        try:
            payload = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return json_error("Malformed JSON body.", status=400)

        filename = os.path.basename((payload.get("filename") or "").strip())
        dest_path = (payload.get("dest_path") or filename).strip()
        try:
            total_size = int(payload.get("total_size") or 0)
        except (TypeError, ValueError):
            return json_error("total_size must be an integer.", status=400)

        if not filename:
            return json_error("filename is required.", status=400)
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTS:
            return json_error("File type '%s' is not allowed." % (ext or filename), status=400)
        if total_size <= 0:
            return json_error("total_size must be greater than zero.", status=400)

        max_bytes = self._config("max_upload_mb", DEFAULT_MAX_MB) * 1024 * 1024
        if total_size > max_bytes:
            return json_error(
                "File is too large (limit %s MB)." % (max_bytes // (1024 * 1024)), status=413)

        if self._safe_dest_path(project, dest_path) is None:
            return json_error("Invalid destination path.", status=400)

        chunk_size = self._config("upload_chunk_mb", DEFAULT_CHUNK_MB) * 1024 * 1024
        total_chunks = max(1, math.ceil(total_size / chunk_size))
        upload_id = uuid.uuid4().hex
        upload_dir = os.path.join(self._uploads_root(project), upload_id)
        os.makedirs(upload_dir, mode=0o700, exist_ok=True)
        meta = {
            "filename": filename, "dest_path": dest_path, "total_size": total_size,
            "chunk_size": chunk_size, "total_chunks": total_chunks,
            "created": time.time(),
        }
        with open(os.path.join(upload_dir, "meta.json"), "w") as f:
            json.dump(meta, f)

        return json_response({
            "upload_id": upload_id, "chunk_size": chunk_size, "total_chunks": total_chunks,
        })

    @http.route("/vibecoder/project/<int:project_id>/upload/chunk",
                type="http", auth="public", csrf=False, methods=["POST"])
    def upload_chunk(self, project_id, upload_id=None, chunk_index=None, **kw):
        _partner, project = self._own_project(project_id)
        if not project:
            return json_error("Project not found.", status=404)

        meta, upload_dir = self._load_meta(project, upload_id)
        if meta is None:
            return json_error("Unknown or expired upload_id.", status=409)

        try:
            idx = int(chunk_index)
        except (TypeError, ValueError):
            return json_error("chunk_index must be an integer.", status=400)
        if idx < 0 or idx >= meta["total_chunks"]:
            return json_error("chunk_index out of range.", status=400)

        f = request.httprequest.files.get("chunk")
        data = f.read() if f else request.httprequest.get_data()
        if not data:
            return json_error("Empty chunk.", status=400)
        if len(data) > meta["chunk_size"] + 1024:  # small slack for encoding overhead
            return json_error("Chunk exceeds configured chunk size.", status=413)

        part_path = os.path.join(upload_dir, "part_%05d" % idx)
        fd = os.open(part_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as out:
            out.write(data)

        return json_response({"received": idx})

    @http.route("/vibecoder/project/<int:project_id>/upload/complete",
                type="http", auth="public", csrf=False, methods=["POST"])
    def upload_complete(self, project_id, **kw):
        _partner, project = self._own_project(project_id)
        if not project:
            return json_error("Project not found.", status=404)

        try:
            payload = json.loads(request.httprequest.get_data() or b"{}")
        except ValueError:
            return json_error("Malformed JSON body.", status=400)
        upload_id = payload.get("upload_id")

        meta, upload_dir = self._load_meta(project, upload_id)
        if meta is None:
            return json_error("Unknown or expired upload_id.", status=409)

        parts = []
        for idx in range(meta["total_chunks"]):
            part_path = os.path.join(upload_dir, "part_%05d" % idx)
            if not os.path.isfile(part_path):
                return json_error(
                    "Upload incomplete: missing chunk %s of %s." % (idx, meta["total_chunks"]),
                    status=409)
            parts.append(part_path)

        dest_full = self._safe_dest_path(project, meta["dest_path"])
        if dest_full is None:
            return json_error("Invalid destination path.", status=400)

        os.makedirs(os.path.dirname(dest_full), exist_ok=True)
        tmp_path = dest_full + ".vibecoder_upload_tmp"
        total_written = 0
        try:
            with open(tmp_path, "wb") as out:
                for part_path in parts:
                    with open(part_path, "rb") as pf:
                        while True:
                            buf = pf.read(1024 * 1024)
                            if not buf:
                                break
                            out.write(buf)
                            total_written += len(buf)
            if total_written != meta["total_size"]:
                os.remove(tmp_path)
                return json_error(
                    "Reassembled size (%s) does not match expected size (%s)."
                    % (total_written, meta["total_size"]), status=409)
            os.replace(tmp_path, dest_full)
        except OSError as e:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
            return json_error("Could not write file: %s" % e, status=500)

        for part_path in parts:
            try:
                os.remove(part_path)
            except OSError:
                pass
        try:
            os.remove(os.path.join(upload_dir, "meta.json"))
            os.rmdir(upload_dir)
        except OSError:
            pass

        return json_response({"ok": True, "path": meta["dest_path"], "size": total_written})

    def _load_meta(self, project, upload_id):
        if not upload_id or not re.fullmatch(r"[0-9a-f]{32}", upload_id):
            return None, None
        upload_dir = os.path.join(self._uploads_root(project), upload_id)
        meta_path = os.path.join(upload_dir, "meta.json")
        if not os.path.isfile(meta_path):
            return None, None
        with open(meta_path) as f:
            return json.load(f), upload_dir
