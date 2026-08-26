/* Cadastro de usuário: pessoa de referência não precisa de senha. */
(function () {
  "use strict";
  var referencia = document.getElementById("somente_referencia");
  if (!referencia) return;

  var blocoSenha = document.getElementById("bloco-senha");
  var envio = document.getElementById("pode_enviar_email");

  function alternar() {
    if (blocoSenha) blocoSenha.hidden = referencia.checked;
    if (envio) {
      envio.disabled = referencia.checked;
      if (referencia.checked) envio.checked = false;
    }
  }

  referencia.addEventListener("change", alternar);
  alternar();
})();
