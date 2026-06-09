/** @odoo-module **/
import { registry } from "@web/core/registry";

/**
 * Subscribes once to the "claudoo" bus notifications and fans them out to
 * the currently-open chat component, keyed by session_id.
 */
export const aiAssistantService = {
    dependencies: ["bus_service"],
    start(env, { bus_service }) {
        const handlers = new Map(); // session_id -> callback

        bus_service.subscribe("claudoo", (payload) => {
            const cb = handlers.get(payload.session_id);
            if (cb) {
                cb(payload);
            }
        });
        bus_service.start();

        return {
            register: (sessionId, cb) => handlers.set(sessionId, cb),
            unregister: (sessionId) => handlers.delete(sessionId),
        };
    },
};

registry.category("services").add("claudoo", aiAssistantService);
