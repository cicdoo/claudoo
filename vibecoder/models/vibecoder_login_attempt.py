# -*- coding: utf-8 -*-
import time

from odoo import api, fields, models

# Exponential back-off thresholds: index = failed attempts within the window,
# value = seconds the caller must wait before trying again.
BACKOFF_SCHEDULE = [0, 0, 0, 2, 4, 8, 16, 32, 60]
WINDOW_SECONDS = 15 * 60


class VibecoderLoginAttempt(models.Model):
    _name = "vibecoder.login_attempt"
    _description = "Vibecoder Login Attempt Throttle"

    key = fields.Char(required=True, index=True, help="login+ip composite key")
    fail_count = fields.Integer(default=0)
    last_attempt = fields.Float(default=0.0, help="epoch seconds")

    @api.model
    def _make_key(self, login, ip):
        return "%s|%s" % ((login or "").strip().lower(), ip or "")

    @api.model
    def check_and_touch(self, login, ip):
        """Raise nothing; return the number of seconds the caller must still
        wait (0 = allowed now). Call ``register_failure``/``register_success``
        after the actual credential check."""
        key = self._make_key(login, ip)
        rec = self.sudo().search([("key", "=", key)], limit=1)
        if not rec:
            return 0
        elapsed = time.time() - rec.last_attempt
        idx = min(rec.fail_count, len(BACKOFF_SCHEDULE) - 1)
        wait = BACKOFF_SCHEDULE[idx] - elapsed
        return max(0, wait)

    @api.model
    def register_failure(self, login, ip):
        key = self._make_key(login, ip)
        rec = self.sudo().search([("key", "=", key)], limit=1)
        now = time.time()
        if rec:
            # Reset the counter once the window has elapsed since last failure.
            if now - rec.last_attempt > WINDOW_SECONDS:
                rec.write({"fail_count": 1, "last_attempt": now})
            else:
                rec.write({"fail_count": rec.fail_count + 1, "last_attempt": now})
        else:
            self.sudo().create({"key": key, "fail_count": 1, "last_attempt": now})

    @api.model
    def register_success(self, login, ip):
        key = self._make_key(login, ip)
        self.sudo().search([("key", "=", key)]).unlink()

    @api.model
    def _cron_gc(self):
        cutoff = time.time() - WINDOW_SECONDS * 4
        self.sudo().search([("last_attempt", "<", cutoff)]).unlink()
