"use strict";
const form = document.querySelector("#login-form"),
  status = document.querySelector("#login-status");
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = form.querySelector("button");
  button.disabled = true;
  status.textContent = "Signing in…";
  try {
    const response = await fetch("/console/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: form.username.value,
        password: form.password.value,
      }),
    });
    form.password.value = "";
    if (!response.ok) {
      status.textContent =
        response.status === 429
          ? "Too many attempts. Try again after the local ten-minute limit."
          : "Sign-in was not accepted. Check your local credentials.";
      return;
    }
    location.assign("/console");
  } catch {
    status.textContent =
      "The local service is unavailable. No sign-in was completed.";
  } finally {
    button.disabled = false;
  }
});
