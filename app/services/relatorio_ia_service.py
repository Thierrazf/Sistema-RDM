"""Geração de análises gerenciais a partir de métricas agregadas."""

import base64
import hashlib
import ipaddress
import json
import math
import socket
import time
from urllib.parse import urlsplit

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from ..models import ConfiguracaoIA

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
GEMINI_GENERATE_CONTENT_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
PROVEDORES = {"openai", "anthropic", "gemini", "openai_compatible"}
INSTRUCAO_SISTEMA = (
    "Você é um analista de gestão de mudanças e continuidade. Produza em português "
    "um relatório objetivo com resumo executivo, tendências e pontos de atenção. "
    "Não inclua sugestões, recomendações, planos de ação ou prescrições. Baseie-se "
    "exclusivamente nos números enviados; não invente causas, impactos ou fatos. "
    "Avise quando a amostra for pequena e diferencie correlação de causalidade."
)


class ErroConfiguracaoIA(ValueError):
    """Configuração da integração ausente ou inválida."""


class ErroRelatorioIA(RuntimeError):
    """Falha ao solicitar ou interpretar uma análise do provedor."""


def _fernet() -> Fernet:
    segredo = current_app.config.get("SECRET_KEY")
    if not segredo:
        raise ErroConfiguracaoIA("A chave de criptografia do sistema não está configurada.")
    chave = base64.urlsafe_b64encode(hashlib.sha256(str(segredo).encode()).digest())
    return Fernet(chave)


def cifrar_api_key(api_key: str) -> str:
    return _fernet().encrypt(api_key.encode()).decode()


def decifrar_api_key(configuracao: ConfiguracaoIA) -> str:
    if not configuracao.api_key_cifrada:
        raise ErroConfiguracaoIA("Configure uma chave de API na área administrativa.")
    try:
        return _fernet().decrypt(configuracao.api_key_cifrada.encode()).decode()
    except InvalidToken as exc:
        raise ErroConfiguracaoIA(
            "Não foi possível decifrar a chave salva. Cadastre-a novamente; "
            "a chave secreta do sistema pode ter sido alterada."
        ) from exc


def _url_publica_https(url: str) -> str:
    """Valida endpoint customizado para evitar SSRF a serviços internos."""
    try:
        partes = urlsplit(url)
        hostname = partes.hostname
        porta = partes.port
    except ValueError as exc:
        raise ErroConfiguracaoIA("A URL da API compatível é inválida.") from exc

    if (
        partes.scheme != "https"
        or not hostname
        or partes.username
        or partes.password
        or partes.query
        or partes.fragment
        or (porta is not None and porta != 443)
    ):
        raise ErroConfiguracaoIA(
            "O endpoint compatível precisa ser uma URL HTTPS pública, sem credenciais "
            "ou parâmetros."
        )

    hostname = hostname.rstrip(".").lower()
    try:
        enderecos = {
            ipaddress.ip_address(resultado[4][0].split("%", 1)[0])
            for resultado in socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        }
    except (OSError, ValueError) as exc:
        raise ErroConfiguracaoIA(
            "Não foi possível validar o host público da API compatível."
        ) from exc
    if not enderecos or any(not endereco.is_global for endereco in enderecos):
        raise ErroConfiguracaoIA("O host da API compatível precisa resolver para IPs públicos.")

    caminho = partes.path.rstrip("/")
    if not caminho.endswith("/chat/completions"):
        caminho += "/chat/completions"
    return f"https://{partes.netloc}{caminho}"


def _solicitar(
    url: str,
    headers: dict,
    corpo: dict,
    provedor: str,
    modelo: str,
    api_key: str,
):
    resposta = None
    for tentativa in range(3):
        try:
            resposta = requests.post(
                url,
                headers=headers,
                json=corpo,
                timeout=(5, 45),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise ErroRelatorioIA(
                "Não foi possível conectar ao provedor de IA. Verifique a rede e tente novamente."
            ) from exc

        if provedor != "Gemini" or resposta.status_code != 503 or tentativa == 2:
            break

        retry_after = resposta.headers.get("Retry-After", "")
        try:
            segundos = float(retry_after)
            pausa = min(max(segundos, 0), 5) if math.isfinite(segundos) else 0.5 * (2 ** tentativa)
        except (TypeError, ValueError):
            pausa = 0.5 * (2 ** tentativa)
        time.sleep(pausa)

    if not resposta.ok:
        if resposta.status_code in (401, 403):
            raise ErroRelatorioIA(
                f"{provedor}: chave recusada ou sem permissão para usar o modelo "
                f"'{modelo}'. Confirme a chave e o acesso do projeto."
            )
        if resposta.status_code == 429:
            raise ErroRelatorioIA(
                f"{provedor}: limite ou cota atingido. Verifique o plano e tente mais tarde."
            )
        if resposta.status_code == 503 and provedor == "Gemini":
            raise ErroRelatorioIA(
                "Gemini está temporariamente indisponível (HTTP 503), mesmo após "
                "3 tentativas. Tente gerar o relatório novamente em alguns minutos. "
                "Se o erro persistir, verifique o status da Gemini API."
            )
        if 300 <= resposta.status_code < 400:
            raise ErroRelatorioIA("O endpoint retornou redirecionamento, que não é permitido.")
        if resposta.status_code == 404:
            try:
                detalhe = resposta.json().get("error", {}).get("message", "")
            except (ValueError, AttributeError):
                detalhe = ""
            if not isinstance(detalhe, str):
                detalhe = ""
            detalhe = "".join(
                caractere for caractere in detalhe
                if caractere.isprintable()
            ).replace(api_key, "[chave ocultada]")[:350]
            if provedor == "Gemini":
                orientacao = (
                    f"Gemini retornou 404 para o modelo '{modelo}'. Isso geralmente "
                    "significa que o identificador não existe ou não está habilitado "
                    "para esta chave/projeto. Use o ID exato de um modelo que suporte "
                    "generateContent (por exemplo, gemini-3.8-flash) e confirme que a "
                    "chave é da Gemini Developer API."
                )
            else:
                orientacao = (
                    f"{provedor} retornou 404 para o modelo '{modelo}'. Confira o "
                    "identificador e se ele está disponível para esta chave/projeto."
                )
            if detalhe:
                orientacao += f" Detalhe do provedor: {detalhe}"
            raise ErroRelatorioIA(orientacao)
        raise ErroRelatorioIA(
            f"{provedor} retornou erro HTTP {resposta.status_code}."
        )
    try:
        return resposta.json()
    except ValueError as exc:
        raise ErroRelatorioIA("A resposta do provedor de IA não é um JSON válido.") from exc


def _extrair_texto(provedor: str, dados: dict) -> str:
    try:
        if provedor in ("openai", "openai_compatible"):
            texto = dados["choices"][0]["message"]["content"]
            if isinstance(texto, list):
                texto = "\n".join(
                    parte["text"] for parte in texto
                    if isinstance(parte, dict) and isinstance(parte.get("text"), str)
                )
        elif provedor == "anthropic":
            texto = "\n".join(
                bloco["text"] for bloco in dados["content"]
                if isinstance(bloco, dict) and bloco.get("type") == "text"
            )
        else:
            texto = "\n".join(
                parte["text"]
                for parte in dados["candidates"][0]["content"]["parts"]
                if isinstance(parte, dict) and isinstance(parte.get("text"), str)
            )
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ErroRelatorioIA("A resposta do provedor veio em formato inesperado.") from exc
    if not isinstance(texto, str) or not texto.strip():
        raise ErroRelatorioIA("O provedor de IA não retornou conteúdo para o relatório.")
    return texto.strip()


def gerar_relatorio(configuracao: ConfiguracaoIA, metricas: dict) -> str:
    provedor = configuracao.provedor or "openai"
    if provedor not in PROVEDORES:
        raise ErroConfiguracaoIA("O provedor salvo não é suportado.")
    api_key = decifrar_api_key(configuracao)
    dados_metricas = json.dumps(metricas, ensure_ascii=False)
    pergunta = (
        "Analise estas métricas agregadas de crises e RDMs. Não há dados pessoais "
        "nem descrições de ocorrências.\n" + dados_metricas
    )
    modelo = configuracao.modelo

    if provedor in ("openai", "openai_compatible"):
        if provedor == "openai":
            url = OPENAI_CHAT_COMPLETIONS_URL
        else:
            url = _url_publica_https(configuracao.url_compativel or "")
        corpo = {
            "model": modelo,
            "messages": [
                {"role": "system", "content": INSTRUCAO_SISTEMA},
                {"role": "user", "content": pergunta},
            ],
            "temperature": 0.3,
            "max_completion_tokens": 1400,
            "store": False,
        }
        if provedor == "openai_compatible":
            corpo.pop("max_completion_tokens")
            corpo.pop("store")
            corpo["max_tokens"] = 1400
        nome_provedor = (
            "OpenAI" if provedor == "openai"
            else "API compatível com OpenAI"
        )
        dados = _solicitar(
            url, {"Authorization": f"Bearer {api_key}"}, corpo,
            nome_provedor, modelo, api_key,
        )
    elif provedor == "anthropic":
        dados = _solicitar(
            ANTHROPIC_MESSAGES_URL,
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            {
                "model": modelo,
                "max_tokens": 1400,
                "temperature": 0.3,
                "system": INSTRUCAO_SISTEMA,
                "messages": [{"role": "user", "content": pergunta}],
            },
            "Claude",
            modelo,
            api_key,
        )
    else:
        url = GEMINI_GENERATE_CONTENT_URL.format(model=modelo)
        dados = _solicitar(
            url,
            {"x-goog-api-key": api_key},
            {
                "systemInstruction": {"parts": [{"text": INSTRUCAO_SISTEMA}]},
                "contents": [{"role": "user", "parts": [{"text": pergunta}]}],
                "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1400},
            },
            "Gemini",
            modelo,
            api_key,
        )
    return _extrair_texto(provedor, dados)
