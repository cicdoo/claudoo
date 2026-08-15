async function vcLoadProjects() {
    const list = document.getElementById("vc-project-list");
    const { projects } = await vcRpc("/vibecoder/projects", {});
    list.innerHTML = "";
    if (!projects.length) {
        list.innerHTML = '<div class="vc-card">No projects yet. Create your first one above.</div>';
        return;
    }
    for (const p of projects) {
        const row = document.createElement("div");
        row.className = "vc-project-row";
        row.innerHTML = `
            <div>
                <div><strong>${vcEscape(p.name)}</strong></div>
                <div style="color:var(--vc-muted);font-size:12px">${vcEscape(p.github_repo_full_name || "")}</div>
            </div>
            <div style="display:flex;align-items:center;gap:10px">
                <span class="vc-badge ${p.state}">${p.state}</span>
                <a href="/vibecoder/project/${p.id}"><button class="vc-secondary" style="width:auto">Open</button></a>
            </div>`;
        list.appendChild(row);
    }
}

function vcEscape(s) {
    const d = document.createElement("div");
    d.textContent = s || "";
    return d.innerHTML;
}

document.addEventListener("DOMContentLoaded", () => {
    vcLoadProjects();
    const form = document.getElementById("vc-new-project-form");
    const err = document.getElementById("vc-error");
    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        err.style.display = "none";
        const name = document.getElementById("vc-project-name").value.trim();
        if (!name) return;
        const btn = form.querySelector("button");
        btn.disabled = true;
        try {
            const { project } = await vcRpc("/vibecoder/projects/create", { name });
            window.location.href = "/vibecoder/project/" + project.id;
        } catch (e) {
            vcShowError(err, e);
            btn.disabled = false;
        }
    });
});
