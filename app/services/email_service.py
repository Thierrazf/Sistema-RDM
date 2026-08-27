"""Montagem e disparo dos e-mails do sistema.

O corpo é sempre renderizado a partir de um template Jinja (nunca f-string no
código), em HTML com alternativa em texto puro. Isso permite pré-visualizar
exatamente o que será enviado antes de disparar.
"""

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from flask import current_app, render_template, url_for

from .graph_service import configurado as graph_configurado
from .graph_service import enviar_graph

# Identificador do logo dentro da mensagem. O Outlook bloqueia imagens
# externas, então o arquivo viaja embutido e o HTML aponta para cid:.
LOGO_CID = "logo"


def caminho_logo() -> Path | None:
    caminho = Path(current_app.root_path) / "static" / "img" / "logo.png"
    return caminho if caminho.exists() else None


TEXTO_PADRAO_RDM = (
    "Prezados,\n\n"
    "Encaminhamos a Requisição de Mudança (RDM) abaixo para ciência e "
    "acompanhamento. A execução seguirá a janela e o plano de trabalho "
    "detalhados neste comunicado, com as atividades distribuídas por equipe "
    "responsável.\n\n"
    "Em caso de indisponibilidade não prevista durante a janela, o plano de "
    "rollback será acionado imediatamente e a equipe comunicará o retorno."
)

TEXTO_PADRAO_ENCERRAMENTO = (
    "Informamos o encerramento da Requisição de Mudança abaixo. "
    "Todas as atividades previstas foram concluídas e os serviços validados."
)


TEXTOS_ENCERRAMENTO = {
    "SUCESSO": (
        "Prezados,\n\n"
        "Informamos o encerramento da Requisição de Mudança abaixo. Todas as "
        "atividades previstas foram executadas dentro da janela programada e os "
        "serviços foram validados pelas equipes responsáveis.\n\n"
        "Não houve necessidade de acionar o plano de rollback. Os sistemas "
        "envolvidos permanecem em operação normal."
    ),
    "SUCESSO_RESSALVA": (
        "Prezados,\n\n"
        "Informamos o encerramento da Requisição de Mudança abaixo. As atividades "
        "previstas foram executadas e os serviços estão em operação, porém com "
        "ressalvas registradas durante a janela — detalhadas no relato abaixo.\n\n"
        "As pendências identificadas serão tratadas pelas equipes responsáveis e "
        "acompanhadas até a conclusão."
    ),
    "ROLLBACK": (
        "Prezados,\n\n"
        "Informamos que a Requisição de Mudança abaixo NÃO foi concluída. Durante a "
        "execução foi necessário acionar o plano de rollback, e o ambiente foi "
        "restaurado ao estado anterior à mudança.\n\n"
        "Os serviços encontram-se operando na configuração original. A causa da "
        "falha está sendo apurada e uma nova janela será programada após a análise, "
        "com abertura de nova RDM."
    ),
    "NAO_EXECUTADA": (
        "Prezados,\n\n"
        "Informamos que a Requisição de Mudança abaixo não chegou a ser executada e "
        "está sendo encerrada sem alteração no ambiente.\n\n"
        "Nenhum serviço foi impactado. O motivo está registrado no relato abaixo e, "
        "caso a mudança siga necessária, será reprogramada em nova janela."
    ),
}


def texto_padrao_encerramento(resultado) -> str:
    """Texto de abertura sugerido conforme o desfecho da janela."""
    chave = getattr(resultado, "name", str(resultado or ""))
    return TEXTOS_ENCERRAMENTO.get(chave, TEXTOS_ENCERRAMENTO["SUCESSO"])


# --------------------------------------------------------------------- envio
def _montar_mensagem(destinatarios, assunto, html, texto, anexos=None):
    cfg = current_app.config
    remetente = cfg["EMAIL_REMETENTE"] or cfg["SMTP_USER"]
    if not remetente:
        raise RuntimeError(
            "EMAIL_REMETENTE não configurado. Defina no .env antes de enviar."
        )

    msg = EmailMessage()
    msg["Subject"] = assunto
    msg["From"] = formataddr((cfg["EMAIL_NOME_REMETENTE"], remetente))
    msg["To"] = ", ".join(destinatarios)
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")

    # O logo entra como parte relacionada à versão HTML, não como anexo solto.
    logo = caminho_logo()
    if logo:
        msg.get_payload()[-1].add_related(
            logo.read_bytes(), maintype="image", subtype="png", cid=f"<{LOGO_CID}>"
        )
    for caminho in anexos or []:
        p = Path(caminho)
        if not p.exists():
            continue
        msg.add_attachment(
            p.read_bytes(), maintype="application", subtype="pdf", filename=p.name
        )
    return msg


def _entregar(app, msg):
    cfg = app.config
    contexto = ssl.create_default_context()
    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=contexto)
            smtp.ehlo()
            if cfg["SMTP_USER"]:
                smtp.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"])
            smtp.send_message(msg)
        app.logger.info("E-mail entregue: %s", msg["To"])
        return True, ""
    except Exception as exc:  # noqa: BLE001 — a falha precisa virar log, não 500
        app.logger.error("Falha no envio de e-mail: %s", exc)
        return False, str(exc)


def backend_ativo(cfg=None) -> str:
    """Qual mecanismo de envio está em uso: 'graph' ou 'smtp'."""
    cfg = cfg or current_app.config
    escolhido = (cfg.get("EMAIL_BACKEND") or "auto").lower()
    if escolhido == "graph":
        return "graph"
    if escolhido == "smtp":
        return "smtp"
    # auto: usa a Graph quando as credenciais estão presentes.
    return "graph" if graph_configurado(cfg) else "smtp"


def enviar(destinatarios, assunto, html, texto, anexos=None, assincrono=False):
    """Envia o e-mail e devolve (ok, erro).

    O envio é síncrono por padrão: a tela precisa poder dizer a verdade sobre o
    que aconteceu. Um comunicado de RDM que falhou silenciosamente é pior do
    que alguns segundos de espera.
    """
    if backend_ativo() == "graph":
        logo = caminho_logo()
        return enviar_graph(
            destinatarios, assunto, html, texto, anexos,
            logo=str(logo) if logo else None,
            logo_cid=LOGO_CID if logo else None,
        )

    msg = _montar_mensagem(destinatarios, assunto, html, texto, anexos)
    app = current_app._get_current_object()

    if assincrono:
        from threading import Thread

        Thread(target=_entregar, args=(app, msg), daemon=True).start()
        return True, ""
    return _entregar(app, msg)


# ----------------------------------------------------------------------- RDM
def _origem_logo(preview: bool) -> str | None:
    """Endereço da imagem no HTML.

    No envio o logo viaja embutido e é referenciado por cid:. Na tela de
    pré-visualização isso não resolve, então lá vale o arquivo estático.
    """
    if not caminho_logo():
        return None
    if preview:
        return url_for("static", filename="img/logo.png")
    return f"cid:{LOGO_CID}"

def montar_email_rdm(rdm, texto_introducao=None, observacao=None, preview=False):
    """Devolve (assunto, html, texto) — usado tanto no preview quanto no envio."""
    contexto = {
        "rdm": rdm,
        "introducao": (texto_introducao or TEXTO_PADRAO_RDM).strip(),
        "observacao": (observacao or "").strip(),
        "grupos": rdm.atividades_por_equipe(),
        "assinatura": current_app.config["EMAIL_NOME_REMETENTE"],
        "logo_src": _origem_logo(preview),
    }
    janela = rdm.inicio_previsto.strftime("%d/%m/%Y %H:%M") if rdm.inicio_previsto else "a definir"
    assunto = f"[{rdm.identificador}] {rdm.titulo} — janela {janela}"
    html = render_template("email/rdm.html", **contexto)
    texto = render_template("email/rdm.txt", **contexto)
    return assunto, html, texto


def enviar_rdm(rdm, destinatarios, texto_introducao=None, observacao=None, anexo_pdf=None):
    assunto, html, texto = montar_email_rdm(rdm, texto_introducao, observacao)
    copia = current_app.config.get("EMAIL_COPIA_PADRAO") or []
    todos = list(dict.fromkeys([*destinatarios, *copia]))
    anexos = [anexo_pdf] if anexo_pdf else None
    return enviar(todos, assunto, html, texto, anexos=anexos), todos


# ------------------------------------------------------------- encerramento
def montar_email_encerramento(rdm, texto_introducao=None, observacao=None, preview=False):
    """Comunicado de fechamento da janela, com horas reais e desfecho."""
    contexto = {
        "rdm": rdm,
        "introducao": (texto_introducao or texto_padrao_encerramento(rdm.resultado)).strip(),
        "observacao": (observacao or "").strip(),
        "grupos": rdm.atividades_por_equipe(),
        "assinatura": current_app.config["EMAIL_NOME_REMETENTE"],
        "logo_src": _origem_logo(preview),
    }
    desfecho = rdm.resultado.value if rdm.resultado else "encerrada"
    assunto = f"[{rdm.identificador}] Encerramento — {rdm.titulo} — {desfecho}"
    html = render_template("email/rdm_encerramento.html", **contexto)
    texto = render_template("email/rdm_encerramento.txt", **contexto)
    return assunto, html, texto


def enviar_encerramento(rdm, destinatarios, texto_introducao=None, observacao=None, anexo_pdf=None):
    assunto, html, texto = montar_email_encerramento(rdm, texto_introducao, observacao)
    copia = current_app.config.get("EMAIL_COPIA_PADRAO") or []
    todos = list(dict.fromkeys([*destinatarios, *copia]))
    anexos = [anexo_pdf] if anexo_pdf else None
    return enviar(todos, assunto, html, texto, anexos=anexos), todos


# --------------------------------------------------------------------- Crise
def enviar_crise(crise, destinatarios, anexo_pdf=None):
    assunto = f"[{crise.identificador}] {crise.titulo} — {crise.status}"
    html = render_template("email/crise.html", crise=crise)
    texto = render_template("email/crise.txt", crise=crise)
    anexos = [anexo_pdf] if anexo_pdf else None
    return enviar(destinatarios, assunto, html, texto, anexos=anexos)
