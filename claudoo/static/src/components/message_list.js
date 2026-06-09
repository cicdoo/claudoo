/** @odoo-module **/
import { Component, useRef, onPatched, onMounted } from "@odoo/owl";
import { AiMessage } from "./message";

export class AiMessageList extends Component {
    static template = "claudoo.MessageList";
    static components = { AiMessage };
    static props = { messages: Array, running: Boolean };

    setup() {
        this.scrollRef = useRef("scroll");
        onMounted(() => this._scrollToBottom());
        onPatched(() => this._scrollToBottom());
    }

    _scrollToBottom() {
        const el = this.scrollRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }
}
