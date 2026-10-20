(function () {
  "use strict";

  var error = document.getElementById("register-error");
  var params = new URLSearchParams(location.search);
  var nextTarget = safeNext(params.get("next"));
  var loginLink = document.querySelector('.auth-switch a[href="/login"]');
  if (loginLink && nextTarget) {
    loginLink.href = "/login?next=" + encodeURIComponent(nextTarget);
  }
  document.getElementById("register-form").addEventListener("submit", function (event) {
    event.preventDefault();
    error.hidden = true;
    var password = document.getElementById("register-password").value;
    var confirm = document.getElementById("register-confirm").value;
    if (password !== confirm) {
      error.textContent = "两次输入的密码不一致";
      error.hidden = false;
      return;
    }
    var submit = event.target.querySelector('button[type="submit"]');
    submit.disabled = true;
    fetch("/api/v1/auth/register", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: document.getElementById("register-username").value,
        display_name: document.getElementById("register-display-name").value,
        password: password
      })
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          throw new Error(payload.error || "注册失败");
        }
        location.replace(nextTarget || payload.redirect || "/");
      });
    }).catch(function (reason) {
      error.textContent = reason.message;
      error.hidden = false;
      submit.disabled = false;
    });
  });

  function safeNext(value) {
    if (!value || value.charAt(0) !== "/" || value.charAt(1) === "/") {
      return "";
    }
    return value;
  }
})();
