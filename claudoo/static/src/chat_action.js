/** @odoo-module **/
// Copyright 2026 CICDoo (https://cicdoo.com)
// SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial
// Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { AiMessageList } from "./components/message_list";
import { AiComposer } from "./components/composer";
import { ReportFrame } from "./components/report_frame";
import { extractHtmlBlocks } from "./artifacts";

export class AiChatAction extends Component {
    static template = "claudoo.ChatAction";
    static components = { AiMessageList, AiComposer, ReportFrame };
    static props = ["*"];

    setup() {
        this.aiBus = useService("claudoo");
        this.notification = useService("notification");
        // Odoo 17 exposes RPC as a service (no standalone @web/core/network/rpc).
        this.rpc = useService("rpc");
        this.state = useState({
            sessions: [],
            currentId: null,
            messages: [],
            running: false,
            // Auth gate
            authenticated: false,
            authReady: false, // status check finished
            authStep: "idle", // "idle" -> "awaiting_code" -> "exchanging"
            authError: "",
            authCode: "",
            // Artifact panel (right side): rendered chart/report HTML.
            artifact: null,
            artifactOpen: false,
        });

        onWillStart(async () => {
            const { authenticated } = await this.rpc("/claudoo/auth/status");
            this.state.authenticated = authenticated;
            this.state.authReady = true;
            if (authenticated) {
                await this._initChat();
            }
        });

        onWillUnmount(() => {
            if (this.state.currentId) {
                this.aiBus.unregister(this.state.currentId);
            }
        });
    }

    // ------------------------------------------------------------------
    // Authentication gate
    // ------------------------------------------------------------------
    async _startAuth() {
        this.state.authError = "";
        try {
            const { url } = await this.rpc("/claudoo/auth/start");
            // Open Claude's authorization screen in a new tab.
            window.open(url, "_blank", "noopener,noreferrer");
            this.state.authStep = "awaiting_code";
        } catch (e) {
            this.state.authError =
                e.message?.data?.message || "Could not start the login.";
        }
    }

    async _completeAuth() {
        const code = (this.state.authCode || "").trim();
        if (!code) {
            this.state.authError = "Paste the code from Claude first.";
            return;
        }
        this.state.authError = "";
        this.state.authStep = "exchanging";
        try {
            await this.rpc("/claudoo/auth/complete", { code });
            // Authenticated — drop the gate and slide into the chat.
            this.state.authenticated = true;
            this.state.authCode = "";
            this.state.authStep = "idle";
            await this._initChat();
        } catch (e) {
            this.state.authStep = "awaiting_code";
            this.state.authError =
                e.message?.data?.message || "Authentication failed. Try again.";
        }
    }

    async _initChat() {
        await this._loadSessions();
        if (!this.state.sessions.length) {
            await this._newSession();
        } else {
            await this._openSession(this.state.sessions[0].id);
        }
    }

    async _loadSessions() {
        this.state.sessions = await this.rpc("/claudoo/sessions");
    }

    async _newSession() {
        const s = await this.rpc("/claudoo/new");
        this.state.sessions.unshift(s);
        await this._openSession(s.id);
    }

    async _openSession(id) {
        if (this.state.currentId) {
            this.aiBus.unregister(this.state.currentId);
        }
        this.state.currentId = id;
        this.aiBus.register(id, (p) => this._onBusEvent(p));
        const data = await this.rpc("/claudoo/messages", { session_id: id });
        this.state.messages = data.messages;
        this.state.running = data.state === "running";
        // Surface this conversation's most recent chart/report on the right.
        this.state.artifact = null;
        this.state.artifactOpen = false;
        this._captureLatestArtifact();
    }

    // ------------------------------------------------------------------
    // Artifact panel
    // ------------------------------------------------------------------
    openArtifact(html) {
        this.state.artifact = html;
        this.state.artifactOpen = true;
    }

    closeArtifact() {
        this.state.artifactOpen = false;
    }

    openArtifactNewTab() {
        if (!this.state.artifact) {
            return;
        }
        const blob = new Blob([this.state.artifact], { type: "text/html" });
        const url = URL.createObjectURL(blob);
        window.open(url, "_blank", "noopener,noreferrer");
        setTimeout(() => URL.revokeObjectURL(url), 60000);
    }

    // The HTML to show for a message, or null if it carries none.
    _messageArtifact(msg) {
        if (!msg) {
            return null;
        }
        if (msg.role === "report") {
            return msg.body || null;
        }
        if (msg.role === "assistant") {
            const blocks = extractHtmlBlocks(msg.body || "");
            return blocks.length ? blocks[blocks.length - 1] : null;
        }
        return null;
    }

    // Auto-open the chart/report from a freshly streamed message.
    _maybeCaptureArtifact(msg) {
        const html = this._messageArtifact(msg);
        if (html) {
            this.openArtifact(html);
        }
    }

    // Scan history (newest first) and open the latest artifact, if any.
    _captureLatestArtifact() {
        for (let i = this.state.messages.length - 1; i >= 0; i--) {
            const html = this._messageArtifact(this.state.messages[i]);
            if (html) {
                this.openArtifact(html);
                return;
            }
        }
    }

    _upsertMessage(msg) {
        const idx = this.state.messages.findIndex((m) => m.id === msg.id);
        if (idx === -1) {
            this.state.messages.push(msg);
        } else {
            this.state.messages[idx] = msg;
        }
    }

    _onBusEvent(p) {
        switch (p.kind) {
            case "started":
                this.state.running = true;
                break;
            case "message":
                this._upsertMessage(p.message);
                this._maybeCaptureArtifact(p.message);
                break;
            case "done":
                this.state.running = false;
                this._reload();
                break;
            case "error":
                this.state.running = false;
                this.state.messages.push({
                    id: `err-${Date.now()}`,
                    role: "error",
                    body: p.error || "Something went wrong.",
                    tool_calls: [],
                });
                break;
        }
    }

    async _reload() {
        if (!this.state.currentId) return;
        const data = await this.rpc("/claudoo/messages", {
            session_id: this.state.currentId,
        });
        this.state.messages = data.messages;
    }

    async onSend(text, files = []) {
        // Optimistic user bubble; the assistant reply arrives over the bus.
        this.state.messages.push({
            id: `tmp-${Date.now()}`,
            role: "user",
            body: text,
            tool_calls: [],
            attachments: files,
        });
        this.state.running = true;
        try {
            await this.rpc("/claudoo/send", {
                session_id: this.state.currentId,
                body: text,
                attachment_ids: files.map((f) => f.id),
            });
        } catch (e) {
            this.state.running = false;
            this.notification.add(e.message?.data?.message || "Failed to send.", {
                type: "danger",
            });
        }
    }

    async onStop() {
        await this.rpc("/claudoo/stop", { session_id: this.state.currentId });
        this.state.running = false;
    }
}

registry.category("actions").add("claudoo.chat", AiChatAction);
