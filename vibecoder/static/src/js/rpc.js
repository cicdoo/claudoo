// Minimal Odoo JSON-RPC 2.0 client for the Vibecoder public site (no `web`
// module dependency, so we can't use Odoo's own rpc helper).
async function vcRpc(url, params) {
    const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", method: "call", params: params || {} }),
    });
    const data = await resp.json();
    if (data.error) {
        const msg = (data.error.data && data.error.data.message) || data.error.message || "Request failed.";
        throw new Error(msg);
    }
    return data.result;
}

function vcShowError(el, err) {
    if (!el) return;
    el.textContent = err.message || String(err);
    el.style.display = "block";
}
