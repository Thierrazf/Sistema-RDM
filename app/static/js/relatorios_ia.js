"use strict";

const provedor = document.getElementById("provedor");
const campoUrl = document.getElementById("campo-url-compativel");
const urlApi = document.getElementById("url_compativel");

function atualizarCampoUrl() {
  const compativel = provedor.value === "openai_compatible";
  campoUrl.hidden = !compativel;
  urlApi.required = compativel;
}

provedor.addEventListener("change", atualizarCampoUrl);
atualizarCampoUrl();
