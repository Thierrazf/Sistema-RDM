/* Formulário de RDM: navegação por etapas e plano de trabalho dinâmico. */
(function () {
  "use strict";

  var form = document.getElementById("form-rdm");
  if (!form) return;

  var molde = document.getElementById("molde-atividade");

  // ------------------------------------------------------------ etapas
  var abas = Array.prototype.slice.call(document.querySelectorAll(".etapa-aba"));
  var paineis = Array.prototype.slice.call(document.querySelectorAll(".etapa-painel"));
  var atual = 1;

  function mostrarEtapa(numero) {
    atual = Math.min(Math.max(numero, 1), abas.length);
    abas.forEach(function (aba) {
      aba.setAttribute("aria-selected", String(Number(aba.dataset.etapa) === atual));
    });
    paineis.forEach(function (painel) {
      painel.hidden = Number(painel.dataset.painel) !== atual;
    });
    document.getElementById("etapa-anterior").disabled = atual === 1;
    document.getElementById("etapa-proxima").disabled = atual === abas.length;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  abas.forEach(function (aba) {
    aba.addEventListener("click", function () {
      mostrarEtapa(Number(aba.dataset.etapa));
    });
  });
  document.getElementById("etapa-anterior").addEventListener("click", function () {
    mostrarEtapa(atual - 1);
  });
  document.getElementById("etapa-proxima").addEventListener("click", function () {
    mostrarEtapa(atual + 1);
  });

  // ------------------------------------------------- plano de trabalho
  function blocos() {
    return Array.prototype.slice.call(document.querySelectorAll(".equipe-bloco"));
  }

  function minutosDaLinha(linha) {
    var horas = parseInt(linha.querySelector('[name="atv_duracao_h"]').value, 10);
    var minutos = parseInt(linha.querySelector('[name="atv_duracao_m"]').value, 10);
    return (isNaN(horas) ? 0 : horas) * 60 + (isNaN(minutos) ? 0 : minutos);
  }

  function atualizar() {
    var ordem = 0;
    var total = 0;

    blocos().forEach(function (bloco) {
      var linhas = bloco.querySelectorAll(".atividade-linha");
      bloco.querySelector(".equipe-vazia").hidden = linhas.length > 0;

      Array.prototype.forEach.call(linhas, function (linha) {
        ordem += 1;
        linha.querySelector(".atividade-ordem").textContent = ordem;
        total += minutosDaLinha(linha);
      });
    });

    var horas = Math.floor(total / 60);
    var minutos = total % 60;
    var texto = total === 0 ? "0 min"
      : horas && minutos ? horas + "h" + String(minutos).padStart(2, "0")
      : horas ? horas + "h"
      : minutos + " min";
    document.getElementById("duracao-total").textContent = texto;
  }

  function adicionar(bloco, dados) {
    var linha = molde.content.firstElementChild.cloneNode(true);
    linha.querySelector('input[name="atv_equipe"]').value = bloco.dataset.equipeNome;

    if (dados) {
      linha.querySelector('textarea[name="atv_descricao"]').value = dados.descricao || "";
      linha.querySelector('input[name="atv_rollback"]').value = dados.rollback || "";
      var minutos = parseInt(dados.duracao, 10);
      if (!isNaN(minutos)) {
        linha.querySelector('[name="atv_duracao_h"]').value = Math.floor(minutos / 60);
        linha.querySelector('[name="atv_duracao_m"]').value = minutos % 60;
      }
    }

    bloco.querySelector(".linhas").appendChild(linha);
    atualizar();
    linha.querySelector('textarea[name="atv_descricao"]').focus();
  }

  blocos().forEach(function (bloco) {
    bloco.querySelector(".adicionar-linha").addEventListener("click", function () {
      adicionar(bloco, null);
    });

    bloco.querySelector(".seletor-catalogo").addEventListener("change", function (evento) {
      var opcao = evento.target.selectedOptions[0];
      if (!opcao || !opcao.value) return;
      adicionar(bloco, {
        descricao: opcao.dataset.descricao,
        duracao: opcao.dataset.duracao,
        rollback: opcao.dataset.rollback,
      });
      evento.target.value = "";
    });
  });

  form.addEventListener("click", function (evento) {
    if (!evento.target.classList.contains("remover-linha")) return;
    evento.target.closest(".atividade-linha").remove();
    atualizar();
  });

  form.addEventListener("input", function (evento) {
    if (evento.target.classList.contains("campo-duracao")) atualizar();
  });

  // Se o analista for escolhido da lista, o campo de nome livre é dispensado.
  form.addEventListener("change", function (evento) {
    if (evento.target.name !== "atv_analista_id") return;
    var campoNome = evento.target
      .closest(".atividade-linha")
      .querySelector('input[name="atv_analista_nome"]');
    campoNome.disabled = Boolean(evento.target.value);
    if (evento.target.value) campoNome.value = "";
  });

  // Leva o usuário direto ao campo com problema, em qualquer etapa.
  form.addEventListener("submit", function (evento) {
    var invalido = form.querySelector(":invalid");
    if (!invalido) return;
    evento.preventDefault();
    var painel = invalido.closest(".etapa-painel");
    if (painel) mostrarEtapa(Number(painel.dataset.painel));
    invalido.focus();
    invalido.reportValidity();
  });

  // ---------------------------------------------------------- autorizador
  var seletorAutorizador = document.getElementById("autorizador_id");
  var blocoManual = document.getElementById("autorizador-manual");

  function alternarAutorizador() {
    if (!seletorAutorizador || !blocoManual) return;
    var manual = !seletorAutorizador.value;
    blocoManual.hidden = !manual;
    Array.prototype.forEach.call(blocoManual.querySelectorAll("input"), function (campo) {
      campo.disabled = !manual;
    });
  }

  if (seletorAutorizador) {
    seletorAutorizador.addEventListener("change", alternarAutorizador);
    alternarAutorizador();
  }

  mostrarEtapa(1);
  atualizar();
})();
