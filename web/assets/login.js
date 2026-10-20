(function () {
  "use strict";

  var error = document.getElementById("login-error");
  var qrButton = document.getElementById("qr-login-button");
  var qrStatus = document.getElementById("qr-status");
  var qrImage = document.getElementById("qr-image");
  var qrImageWrap = document.getElementById("qr-image-wrap");
  var qrMark = document.getElementById("qr-mark");
  var wechatButton = document.getElementById("wechat-login-button");
  var wechatStatus = document.getElementById("wechat-status");
  var params = new URLSearchParams(location.search);
  var nextTarget = safeNext(params.get("next"));
  var qrTimer = null;
  var qrPollToken = "";
  var qrRequestID = "";

  var registerLink = document.querySelector('.auth-switch a[href="/register"]');
  if (registerLink && nextTarget) {
    registerLink.href = "/register?next=" + encodeURIComponent(nextTarget);
  }
  if (params.get("qr_error")) {
    error.textContent = params.get("qr_error");
    error.hidden = false;
  }
  if (params.get("wechat_error")) {
    error.textContent = params.get("wechat_error");
    error.hidden = false;
  }

  fetch("/api/v1/auth/status", {credentials: "same-origin"})
    .then(function (response) { return response.json(); })
    .then(function (payload) {
      var wechat = payload.wechat_login || {};
      if (wechat.configured) {
        wechatStatus.textContent = "点击后将跳转到微信官方扫码授权页面。";
        wechatButton.disabled = false;
      } else {
        wechatStatus.textContent = wechat.reason || "微信扫码登录尚未配置。";
      }
    })
    .catch(function () {
      wechatStatus.textContent = "无法读取微信登录配置。";
    });

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
        location.replace(nextTarget || payload.redirect || "/");
      });
    }).catch(function (reason) {
      error.textContent = reason.message;
      error.hidden = false;
      submit.disabled = false;
    });
  });

  qrButton.addEventListener("click", startQR);
  wechatButton.addEventListener("click", function () {
    wechatButton.disabled = true;
    wechatStatus.textContent = "正在跳转微信授权…";
    fetch("/api/v1/auth/wechat/start", {credentials: "same-origin"})
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (payload) {
          if (!response.ok) {
            throw new Error(payload.error || "微信登录不可用");
          }
          location.assign(payload.url);
        });
      })
      .catch(function (reason) {
        wechatStatus.textContent = reason.message;
        wechatButton.disabled = false;
      });
  });

  function startQR() {
    clearTimeout(qrTimer);
    qrButton.disabled = true;
    qrButton.textContent = "正在生成…";
    qrStatus.textContent = "正在创建一次性登录请求…";
    fetch("/api/v1/auth/qr/start", {credentials: "same-origin"})
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (payload) {
          if (!response.ok) {
            throw new Error(payload.error || "无法生成二维码");
          }
          qrRequestID = payload.request_id;
          qrPollToken = payload.poll_token;
          qrImage.src = payload.image_data_url;
          qrImageWrap.hidden = false;
          qrMark.hidden = true;
          qrButton.textContent = "刷新二维码";
          qrButton.disabled = false;
          qrStatus.textContent = "等待手机确认。请使用已登录的 Market Trace 手机扫描。";
          pollQR();
        });
      })
      .catch(function (reason) {
        qrButton.textContent = "重新生成";
        qrButton.disabled = false;
        qrStatus.textContent = reason.message;
      });
  }

  function pollQR() {
    if (!qrRequestID || !qrPollToken) {
      return;
    }
    var query = "?request_id=" + encodeURIComponent(qrRequestID) +
      "&poll_token=" + encodeURIComponent(qrPollToken);
    fetch("/api/v1/auth/qr/status" + query, {credentials: "same-origin"})
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (payload) {
          if (!response.ok) {
            throw new Error(payload.error || "扫码状态读取失败");
          }
          if (payload.status === "approved") {
            qrStatus.textContent = "已确认，正在登录…";
            location.replace(nextTarget || payload.redirect || "/");
            return;
          }
          if (payload.status === "expired" || payload.status === "consumed") {
            qrStatus.textContent = payload.status === "expired"
              ? "二维码已过期，请刷新。"
              : "二维码已使用，请刷新。";
            return;
          }
          qrTimer = setTimeout(pollQR, 2000);
        });
      })
      .catch(function (reason) {
        qrStatus.textContent = reason.message;
      });
  }

  function safeNext(value) {
    if (!value || value.charAt(0) !== "/" || value.charAt(1) === "/") {
      return "";
    }
    return value;
  }
})();
