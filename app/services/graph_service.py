"""Envio de e-mail pela Microsoft Graph API.

Alternativa ao SMTP, necessária porque a Microsoft desativou a autenticação
básica (SmtpClientAuthentication) na maioria dos tenants e vai removê-la de vez.

O sistema autentica como aplicação registrada no Entra ID, usando um segredo —
não a senha de uma pessoa. A permissão pode (e deve) ser restrita a uma única
caixa de correio por política de acesso a aplicativo.
"""

import base64
import threading
import time
from pathlib import Path

import requests
from flask import current_app

_TIMEOUT = 30
_ESCOPO = "https://graph.microsoft.com/.default"

# Cache do token em memória: ele vale cerca de uma hora, e pedir um novo a cada
# envio seria desperdício.
_token_cache = {"valor": None, "expira_em": 0.0}
_trava = threading.Lock()


class GraphError(RuntimeError):
    """Falha na obtenção do token ou no envio pela Graph."""


def configurado(cfg=None) -> bool:
    cfg = cfg or current_app.config
    return all(
        cfg.get(chave)
        for chave in ("GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET")
    )


def _obter_token(cfg) -> str:
    agora = time.time()
    with _trava:
        if _token_cache["valor"] and agora < _token_cache["expira_em"]:
            return _token_cache["valor"]

    url = (
        f"https://login.microsoftonline.com/{cfg['GRAPH_TENANT_ID']}"
        "/oauth2/v2.0/token"
    )
    dados = {
        "grant_type": "client_credentials",
        "client_id": cfg["GRAPH_CLIENT_ID"],
        "client_secret": cfg["GRAPH_CLIENT_SECRET"],
        "scope": _ESCOPO,
    }

    try:
        resposta = requests.post(url, data=dados, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise GraphError(f"Não foi possível contatar o Entra ID: {exc}") from exc

    if resposta.status_code != 200:
        raise GraphError(_descrever_erro(resposta, "obter o token"))

    corpo = resposta.json()
    token = corpo.get("access_token")
    if not token:
        raise GraphError("O Entra ID respondeu sem token de acesso.")

    with _trava:
        # Margem de 5 minutos para não usar um token prestes a expirar.
        _token_cache["valor"] = token
        _token_cache["expira_em"] = agora + int(corpo.get("expires_in", 3600)) - 300

    return token


def _descrever_erro(resposta, acao: str) -> str:
    """Traduz o erro da Microsoft para algo acionável."""
    try:
        corpo = resposta.json()
    except ValueError:
        return f"Falha ao {acao}: HTTP {resposta.status_code} — {resposta.text[:300]}"

    erro = corpo.get("error", {})
    if isinstance(erro, str):
        codigo = erro
        mensagem = corpo.get("error_description", "")
    else:
        codigo = erro.get("code", "")
        mensagem = erro.get("message", "")

    dicas = {
        "invalid_client": "O segredo do aplicativo está incorreto ou expirou.",
        "unauthorized_client": "O aplicativo não existe neste tenant.",
        "AADSTS7000215": "Segredo inválido — confira se copiou o Valor, e não o ID do segredo.",
        "AADSTS700016": "O ID do aplicativo não foi encontrado no tenant informado.",
        "ErrorAccessDenied": (
            "O aplicativo não tem permissão Mail.Send, ou o consentimento do "
            "administrador ainda não foi concedido."
        ),
        "ErrorInvalidUser": (
            "A caixa em EMAIL_REMETENTE não existe ou não tem licença de e-mail."
        ),
        "ErrorSendAsDenied": (
            "A política de acesso restringe o aplicativo a outra caixa de correio."
        ),
    }

    dica = ""
    texto_completo = f"{codigo} {mensagem}"
    for chave, explicacao in dicas.items():
        if chave in texto_completo:
            dica = f" — {explicacao}"
            break

    return f"Falha ao {acao}: {codigo or resposta.status_code}. {mensagem}{dica}".strip()


def _anexos(caminhos, logo=None, logo_cid=None) -> list[dict]:
    saida = []
    if logo and logo_cid:
        arquivo_logo = Path(logo)
        if arquivo_logo.exists():
            saida.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": arquivo_logo.name,
                    "contentType": "image/png",
                    "contentBytes": base64.b64encode(arquivo_logo.read_bytes()).decode(),
                    "isInline": True,
                    "contentId": logo_cid,
                }
            )
    for caminho in caminhos or []:
        arquivo = Path(caminho)
        if not arquivo.exists():
            continue
        saida.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": arquivo.name,
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(arquivo.read_bytes()).decode(),
            }
        )
    return saida


def enviar_graph(
    destinatarios, assunto, html, texto, anexos=None,
    logo=None, logo_cid=None, cfg=None
):
    """Envia pela Graph. Devolve (ok, erro) no mesmo formato do SMTP."""
    cfg = cfg or current_app.config

    remetente = cfg.get("EMAIL_REMETENTE")
    if not remetente:
        return False, "EMAIL_REMETENTE não configurado."
    if not configurado(cfg):
        return False, (
            "Credenciais da Graph incompletas. Defina GRAPH_TENANT_ID, "
            "GRAPH_CLIENT_ID e GRAPH_CLIENT_SECRET no .env."
        )

    try:
        token = _obter_token(cfg)
    except GraphError as exc:
        return False, str(exc)

    mensagem = {
        "message": {
            "subject": assunto,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [
                {"emailAddress": {"address": endereco}} for endereco in destinatarios
            ],
            "attachments": _anexos(anexos, logo=logo, logo_cid=logo_cid),
        },
        "saveToSentItems": True,
    }

    url = f"https://graph.microsoft.com/v1.0/users/{remetente}/sendMail"
    try:
        resposta = requests.post(
            url,
            json=mensagem,
            headers={"Authorization": f"Bearer {token}"},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        return False, f"Não foi possível contatar a Graph API: {exc}"

    if resposta.status_code == 202:
        return True, ""

    if resposta.status_code == 401:
        # Token pode ter sido revogado; descarta o cache para a próxima tentativa.
        with _trava:
            _token_cache["valor"] = None

    return False, _descrever_erro(resposta, "enviar a mensagem")
