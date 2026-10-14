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


def gerar_pdf_relatorio_ia(ano: int, relatorio: str, metricas: dict) -> bytes:
    """Gera um PDF de indicadores em memória, sem persistir conteúdo do relatório."""
    fuso = ZoneInfo(current_app.config.get("TIMEZONE", "America/Sao_Paulo"))
    meses = [
        "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
        "Jul", "Ago", "Set", "Out", "Nov", "Dez",
    ]
    crises_por_status = sorted(metricas["crises"]["abertas_por_status"].items())
    crises_por_criticidade = sorted(
        metricas["crises"]["abertas_por_criticidade"].items()
    )
    rdms_por_status = sorted(metricas["rdms"]["situacao_no_ano"].items())
    html = render_template(
        "pdf/relatorio_ia.html",
        ano=ano,
        relatorio=relatorio,
        metricas=metricas,
        serie_crises=[
            (mes, metricas["crises"]["criadas_no_ano_por_mes"][str(indice)])
            for indice, mes in enumerate(meses, start=1)
        ],
        serie_rdms=[
            (mes, metricas["rdms"]["criadas_no_ano_por_mes"][str(indice)])
            for indice, mes in enumerate(meses, start=1)
        ],
        serie_crises_status=crises_por_status or [("Sem dados", 0)],
        serie_crises_criticidade=crises_por_criticidade or [("Sem dados", 0)],
        serie_rdms_status=rdms_por_status or [("Sem dados", 0)],
        emitido_em=agora().astimezone(fuso).strftime("%d/%m/%Y às %H:%M"),
    )
    from weasyprint import HTML

    return HTML(string=html, base_url=str(Path(current_app.root_path))).write_pdf()
