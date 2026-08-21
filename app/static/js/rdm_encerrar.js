/* Tela de encerramento: calcula o tempo real e o desvio conforme se digita. */
(function () {
  "use strict";

  var form = document.getElementById("form-encerrar");
  if (!form) return;

  var previsto = parseInt(document.currentScript.dataset.previsto, 10) || 0;
  var inicio = document.getElementById("inicio_real");
  var fim = document.getElementById("fim_real");
  var saidaTempo = document.getElementById("tempo-real");
  var saidaDesvio = document.getElementById("desvio-real");

  function formatar(total) {
    var h = Math.floor(total / 60);
    var m = total % 60;
    if (h && m) return h + "h" + String(m).padStart(2, "0");
    return h ? h + "h" : m + " min";
  }

  function calcular() {
    if (!inicio.value || !fim.value) {
      saidaTempo.textContent = "—";
      saidaDesvio.textContent = "Comparado com a soma das atividades.";
      return;
    }

    var minutos = Math.round((new Date(fim.value) - new Date(inicio.value)) / 60000);
    if (isNaN(minutos) || minutos < 0) {
      saidaTempo.textContent = "—";
      saidaDesvio.textContent = "O fim precisa ser depois do início.";
      return;
    }

    saidaTempo.textContent = formatar(minutos);

    if (!previsto) {
      saidaDesvio.textContent = "Sem duração prevista para comparar.";
      return;
    }

    var desvio = minutos - previsto;
    if (desvio === 0) {
      saidaDesvio.textContent = "Exatamente dentro do previsto.";
    } else {
      saidaDesvio.textContent =
        formatar(Math.abs(desvio)) + (desvio > 0 ? " acima" : " abaixo") +
        " do previsto (" + formatar(previsto) + ").";
    }
  }

  inicio.addEventListener("input", calcular);
  fim.addEventListener("input", calcular);

  // Marcar rollback quando o resultado for reversão, sem travar a escolha manual.
  form.addEventListener("change", function (evento) {
    if (evento.target.name !== "resultado") return;
    if (evento.target.value === "ROLLBACK") {
      document.getElementById("rollback_acionado").checked = true;
    }
  });

  calcular();
})();
