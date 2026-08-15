function vcInitAuthForm(formId, url, redirectTo) {
    const form = document.getElementById(formId);
    const err = document.getElementById("vc-error");
    form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        err.style.display = "none";
        const fd = new FormData(form);
        const params = Object.fromEntries(fd.entries());
        try {
            await vcRpc(url, params);
            window.location.href = redirectTo;
        } catch (e) {
            vcShowError(err, e);
        }
    });
}
