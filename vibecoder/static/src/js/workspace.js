let vcProjectId = null;
let vcSessionId = null;
let vcLastSeq = 0;
let vcEventSource = null;

function vcEscape(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
}

async function vcInitWorkspace(projectId) {
    vcProjectId = projectId;
    await vcRefreshProject();
    const { sessions } = await vcRpc(`/vibecoder/projects/${projectId}/sessions`, {});
    if (sessions.length) {
        vcSessionId = sessions[0].id;
    } else {
        const s = await vcRpc(`/vibecoder/projects/${projectId}/sessions/new`, {});
        vcSessionId = s.id;
    }
    await vcLoadMessages();
    vcOpenStream();

    document.getElementById("vc-composer-form").addEventListener("submit", vcOnSend);
    document.getElementById("vc-start-btn").addEventListener("click", () => vcStartPreview());
}

async function vcRefreshProject() {
    const { project } = await vcRpc(`/vibecoder/projects/${vcProjectId}`, {});
    const badge = document.getElementById("vc-project-state");
    badge.textContent = project.state;
    badge.className = "vc-badge " + project.state;
    const iframe = document.getElementById("vc-preview-frame");
    if (project.preview_url) {
        if (!iframe.src.includes(project.preview_url)) {
            iframe.src = project.preview_url;
        }
    } else if (project.state === "ready") {
        // Not started yet.
        document.getElementById("vc-start-btn").style.display = "inline-block";
    }
    if (project.state === "creating") {
        setTimeout(vcRefreshProject, 2000);
    }
    if (project.state === "error") {
        vcShowError(document.getElementById("vc-error"), new Error(project.last_error || "Project error."));
    }
    return project;
}

async function vcStartPreview() {
    const btn = document.getElementById("vc-start-btn");
    btn.disabled = true;
    try {
        const { project } = await vcRpc(`/vibecoder/projects/${vcProjectId}/start`, {});
        document.getElementById("vc-preview-frame").src = project.preview_url;
        btn.style.display = "none";
    } catch (e) {
        vcShowError(document.getElementById("vc-error"), e);
    } finally {
        btn.disabled = false;
    }
}

async function vcLoadMessages() {
    const data = await vcRpc(`/vibecoder/session/${vcSessionId}/messages`, {});
    vcLastSeq = data.event_seq || 0;
    const box = document.getElementById("vc-messages");
    box.innerHTML = "";
    for (const m of data.messages) {
        vcAppendMessage(m);
    }
    box.scrollTop = box.scrollHeight;
}

function vcAppendMessage(m) {
    const box = document.getElementById("vc-messages");
    const div = document.createElement("div");
    div.className = "vc-msg " + m.role;
    div.dataset.id = m.id;
    let toolsHtml = "";
    for (const t of (m.tool_calls || [])) {
        toolsHtml += `<span class="vc-tool-chip">${vcEscape(t.name)} ${t.status === "running" ? "…" : "✓"}</span>`;
    }
    div.innerHTML = `<div class="role">${m.role}</div><div class="body">${vcEscape(m.body)}</div>${toolsHtml}`;
    const existing = box.querySelector(`[data-id="${m.id}"]`);
    if (existing) {
        existing.replaceWith(div);
    } else {
        box.appendChild(div);
    }
    box.scrollTop = box.scrollHeight;
}

function vcOpenStream() {
    if (vcEventSource) vcEventSource.close();
    vcEventSource = new EventSource(`/vibecoder/session/${vcSessionId}/stream?after_seq=${vcLastSeq}`);
    vcEventSource.addEventListener("message", (ev) => {
        const m = JSON.parse(ev.data);
        vcLastSeq = Math.max(vcLastSeq, m.id);
        vcAppendMessage(m);
    });
    vcEventSource.addEventListener("done", () => {
        vcEventSource.close();
        document.getElementById("vc-send-btn").disabled = false;
        // "Hot reload": the dev server already serves rebuilt files; just
        // refresh the iframe so the visitor sees the change.
        const iframe = document.getElementById("vc-preview-frame");
        if (iframe.src) iframe.src = iframe.src;
    });
    vcEventSource.addEventListener("timeout", () => {
        vcEventSource.close();
        vcOpenStream(); // keep tailing if the run is still going
    });
    vcEventSource.onerror = () => {
        // Browser EventSource auto-retries; nothing to do.
    };
}

async function vcOnSend(ev) {
    ev.preventDefault();
    const input = document.getElementById("vc-composer-input");
    const body = input.value.trim();
    if (!body) return;
    const err = document.getElementById("vc-error");
    err.style.display = "none";
    document.getElementById("vc-send-btn").disabled = true;
    input.value = "";
    try {
        await vcRpc(`/vibecoder/session/${vcSessionId}/send`, { body });
        await vcLoadMessages();
        vcOpenStream();
    } catch (e) {
        vcShowError(err, e);
        document.getElementById("vc-send-btn").disabled = false;
    }
}
