"""Geração de PDF com WeasyPrint.

Substitui o wkhtmltopdf (projeto arquivado, sem correções de segurança) e
elimina a dependência de binário externo no servidor.
"""

from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app, render_template

from ..models import agora


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
        emitido_em=agora().astimezone(fuso).strftime("%d/%m/%Y às %H:%M"),
    )
    destino = _pasta_pdf() / f"{crise.identificador}.pdf"
    return _renderizar(html, destino)
