/** @odoo-module **/
// Copyright 2026 CICDoo (https://cicdoo.com)
// SPDX-License-Identifier: LGPL-3.0-or-later OR LicenseRef-Claudoo-Commercial
// Dual-licensed: open source (LGPL-3, see LICENSE) or commercial (see COMMERCIAL_LICENSE.md).
import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { AiMessageList } from "./components/message_list";
import { AiComposer } from "./components/composer";

export class AiChatAction extends Component {
    static template = "claudoo.ChatAction";
    static components = { AiMessageList, AiComposer };
    static props = ["*"];

    setup() {
        this.aiBus = useService("claudoo");
        this.notification = useService("notification");
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
        });

        onWillStart(async () => {
            const { authenticated } = await rpc("/claudoo/auth/status");
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
            const { url } = await rpc("/claudoo/auth/start");
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
            await rpc("/claudoo/auth/complete", { code });
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
        this.state.sessions = await rpc("/claudoo/sessions");
    }

    async _newSession() {
        const s = await rpc("/claudoo/new");
        this.state.sessions.unshift(s);
        await this._openSession(s.id);
    }

    async _openSession(id) {
        if (this.state.currentId) {
            this.aiBus.unregister(this.state.currentId);
        }
        this.state.currentId = id;
        this.aiBus.register(id, (p) => this._onBusEvent(p));
        const data = await rpc("/claudoo/messages", { session_id: id });
        this.state.messages = data.messages;
        this.state.running = data.state === "running";
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
        const data = await rpc("/claudoo/messages", {
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
            await rpc("/claudoo/send", {
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
        await rpc("/claudoo/stop", { session_id: this.state.currentId });
        this.state.running = false;
    }
}

registry.category("actions").add("claudoo.chat", AiChatAction);
