(function () {
  "use strict";
  document.getElementById("login-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var error = document.getElementById("login-error");
    error.hidden = true;
    fetch("/login", {
      method: "POST",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({token: document.getElementById("token").value})
    }).then(function (response) {
      if (response.ok) {
        location.replace("/");
        return;
      }
      error.hidden = false;
    }).catch(function () {
      error.hidden = false;
    });
  });
})();
