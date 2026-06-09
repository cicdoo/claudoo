/** @odoo-module **/
import { Component } from "@odoo/owl";
import { renderMarkdown } from "../markdown";

export class AiMessage extends Component {
    static template = "claudoo.Message";
    static props = { message: Object };

    get roleLabel() {
        return { user: "You", assistant: "Assistant", error: "Error" }[
            this.props.message.role
        ] || this.props.message.role;
    }

    // Render assistant/error markdown to HTML; keep user messages as plain text.
    get bodyHtml() {
        return renderMarkdown(this.props.message.body || "");
    }

    get toolCalls() {
        return this.props.message.tool_calls || [];
    }

    get attachments() {
        return this.props.message.attachments || [];
    }

    attachmentIcon(att) {
        const mt = att.mimetype || "";
        if (mt.startsWith("image/")) return "fa-file-image-o";
        if (mt === "application/pdf") return "fa-file-pdf-o";
        return "fa-file-text-o";
    }

    statusIcon(call) {
        if (call.status === "done") return "fa-check text-success";
        if (call.status === "error") return "fa-times text-danger";
        return "fa-spinner fa-spin text-muted";
    }

    summarizeInput(call) {
        try {
            const s = JSON.stringify(call.input || {});
            return s.length > 140 ? s.slice(0, 140) + "…" : s;
        } catch {
            return "";
        }
    }
}
