document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("login-form");
  const errorEl = document.getElementById("auth-error");
  const submit = document.getElementById("auth-submit");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    errorEl.textContent = "";
    submit.disabled = true;
    try {
      await api.post("/api/auth/login", {
        id: document.getElementById("auth-id").value,
        password: document.getElementById("auth-password").value,
      });
      window.location.href = "/admin";
    } catch (err) {
      errorEl.textContent = err.message;
      submit.disabled = false;
    }
  });
});
