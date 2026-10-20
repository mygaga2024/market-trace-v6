(function () {
  "use strict";

  var error = document.getElementById("login-error");
  var qrButton = document.getElementById("qr-login-button");
  var qrStatus = document.getElementById("qr-status");
  var qrTitle = document.getElementById("qr-title");
  var params = new URLSearchParams(location.search);
  if (params.get("qr_error")) {
    error.textContent = params.get("qr_error");
    error.hidden = false;
  }

  document.querySelectorAll("[data-auth-tab]").forEach(function (tab) {
    tab.addEventListener("click", function () {
      var name = tab.getAttribute("data-auth-tab");
      document.querySelectorAll("[data-auth-tab]").forEach(function (item) {
        var active = item === tab;
        item.classList.toggle("active", active);
        item.setAttribute("aria-selected", String(active));
      });
      document.querySelectorAll("[data-auth-pane]").forEach(function (pane) {
        pane.classList.toggle("active", pane.getAttribute("data-auth-pane") === name);
      });
    });
  });

  fetch("/api/v1/auth/status", {credentials: "same-origin"})
    .then(function (response) { return response.json(); })
    .then(function (status) {
      var qr = status.qr_login || {};
      if (qr.configured) {
        qrTitle.textContent = qr.name + " 扫码登录";
        qrStatus.textContent = "点击后将跳转到官方授权页完成扫码。";
        qrButton.disabled = false;
      } else {
        qrStatus.textContent = qr.reason || "官方扫码登录尚未配置。";
      }
    })
    .catch(function () {
      qrStatus.textContent = "无法读取扫码登录配置。";
    });

  document.getElementById("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    error.hidden = true;
    var submit = event.target.querySelector('button[type="submit"]');
    submit.disabled = true;
    fetch("/api/v1/auth/login", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        username: document.getElementById("username").value,
        password: document.getElementById("password").value
      })
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          throw new Error(payload.error || "登录失败");
        }
        location.replace(payload.redirect || "/");
      });
    }).catch(function (reason) {
      error.textContent = reason.message;
      error.hidden = false;
      submit.disabled = false;
    });
  });

  qrButton.addEventListener("click", function () {
    qrButton.disabled = true;
    qrStatus.textContent = "正在创建授权请求…";
    fetch("/api/v1/auth/qr/start", {credentials: "same-origin"})
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (payload) {
          if (!response.ok) {
            throw new Error(payload.error || "扫码登录不可用");
          }
          location.assign(payload.url);
        });
      })
      .catch(function (reason) {
        qrStatus.textContent = reason.message;
        qrButton.disabled = false;
      });
  });
})();
