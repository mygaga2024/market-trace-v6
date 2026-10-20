(function () {
  "use strict";

  var params = new URLSearchParams(location.search);
  var token = params.get("t") || "";
  var button = document.getElementById("approve-button");
  var status = document.getElementById("approve-status");
  var error = document.getElementById("approve-error");
  var title = document.getElementById("approve-title");
  var mark = document.getElementById("approve-mark");

  if (!token) {
    status.textContent = "扫码授权参数缺失，请重新扫描二维码。";
    return;
  }

  fetch("/api/v1/auth/status", {credentials: "same-origin"})
    .then(function (response) { return response.json(); })
    .then(function (payload) {
      if (!payload.authenticated || !payload.user) {
        location.replace("/login?next=" + encodeURIComponent("/qr/approve?t=" + token));
        return;
      }
      status.textContent = "将以「" + (payload.user.display_name || payload.user.username) + "」身份授权另一台设备登录。";
      button.disabled = false;
    })
    .catch(function () {
      status.textContent = "无法读取当前账户，请刷新页面。";
    });

  button.addEventListener("click", function () {
    button.disabled = true;
    error.hidden = true;
    fetch("/api/v1/auth/qr/approve", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: token})
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (payload) {
        if (!response.ok) {
          throw new Error(payload.error || "授权失败");
        }
        title.textContent = "已授权";
        status.textContent = "桌面浏览器已获得登录权限，可以关闭此页面。";
        mark.classList.add("approved");
        button.hidden = true;
      });
    }).catch(function (reason) {
      error.textContent = reason.message;
      error.hidden = false;
      button.disabled = false;
    });
  });
})();
