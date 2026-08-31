"""Geração de PDF com WeasyPrint.

Substitui o wkhtmltopdf (projeto arquivado, sem correções de segurança) e
elimina a dependência de binário externo no servidor.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app, render_template

from ..models import agora


def _logo() -> str | None:
    """Caminho de arquivo do brasão, ou None se ele não estiver presente.

    No PDF não existe servidor web: um caminho como /static/img/logo.png seria
    procurado na raiz do disco. Por isso o endereço vai completo, em file://.
    """
    caminho = Path(current_app.root_path) / "static" / "img" / "logo.png"
    return caminho.as_uri() if caminho.exists() else None

def _pasta_pdf() -> Path:
    pasta = Path(current_app.config["PDF_DIR"])
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def _agora_local() -> str:
    fuso = ZoneInfo(current_app.config.get("TIMEZONE", "America/Sao_Paulo"))
    return agora().astimezone(fuso).strftime("%d/%m/%Y às %H:%M")


def _renderizar(html: str, destino: Path) -> Path:
    from weasyprint import HTML  # import tardio: acelera o boot da aplicação

    HTML(string=html, base_url=str(Path(current_app.root_path))).write_pdf(str(destino))
    return destino


def gerar_pdf_rdm(rdm) -> Path:
    html = render_template(
        "pdf/rdm.html",
        rdm=rdm,
        logo=_logo(),
        grupos=rdm.atividades_por_equipe(),
        emitido_em=_agora_local(),
    )
    destino = _pasta_pdf() / f"{rdm.identificador}.pdf"
    return _renderizar(html, destino)


def gerar_pdf_crise(crise) -> Path:
    fuso = ZoneInfo(current_app.config.get("TIMEZONE", "America/Sao_Paulo"))
    html = render_template(
        "pdf/crise.html",
        crise=crise,
        logo=_logo(),
        emitido_em=agora().astimezone(fuso).strftime("%d/%m/%Y às %H:%M"),
    )
    destino = _pasta_pdf() / f"{crise.identificador}.pdf"
    return _renderizar(html, destino)
