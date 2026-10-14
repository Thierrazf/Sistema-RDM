"""Geração de PDF com WeasyPrint.

Substitui o wkhtmltopdf (projeto arquivado, sem correções de segurança) e
elimina a dependência de binário externo no servidor.
"""

import re
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from flask import current_app, render_template
from markupsafe import Markup, escape

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


def _formatar_relatorio(relatorio: str) -> Markup:
    """Converte a formatação Markdown comum da IA em HTML seguro para o PDF."""
    blocos = []
    paragrafo = []
    itens_lista = []

    def formatar_inline(texto: str) -> str:
        texto = re.sub(r"\*\*(.+?):\*\*", r"**\1**", texto)
        seguro = str(escape(texto))
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", seguro)

    def fechar_paragrafo():
        if paragrafo:
            texto = " ".join(paragrafo)
            blocos.append(f"<p>{formatar_inline(texto)}</p>")
            paragrafo.clear()

    def fechar_lista():
        if itens_lista:
            itens = "".join(f"<li>{formatar_inline(item)}</li>" for item in itens_lista)
            blocos.append(f"<ul>{itens}</ul>")
            itens_lista.clear()

    for linha in relatorio.splitlines():
        texto = linha.strip()
        titulo = re.match(r"^#{1,6}\s*(.*?)\s*#*$", texto)
        if titulo:
            fechar_paragrafo()
            fechar_lista()
            blocos.append(f'<h3 class="analise-titulo">{formatar_inline(titulo.group(1))}</h3>')
        elif re.fullmatch(r"(?:---+|___+|\*\*\*+)", texto):
            fechar_paragrafo()
            fechar_lista()
        elif re.match(r"^[*+-]\s+", texto):
            fechar_paragrafo()
            itens_lista.append(re.sub(r"^[*+-]\s+", "", texto))
        elif not texto:
            fechar_paragrafo()
            fechar_lista()
        else:
            fechar_lista()
            paragrafo.append(texto)

    fechar_paragrafo()
    fechar_lista()
    return Markup("".join(blocos))


def _segmentos_pizza(valores: list[tuple[str, int]]) -> list[dict]:
    total = sum(valor for _, valor in valores)
    if total <= 0:
        return []

    cores = ["#1f4a70", "#a85f06", "#14685a", "#6d3a72", "#9d2220"]
    segmentos = []
    quantidade_segmentos = sum(valor > 0 for _, valor in valores)
    angulo_inicio = -90.0
    for indice, (rotulo, valor) in enumerate(valores):
        if valor <= 0:
            continue
        angulo = 360 * valor / total
        angulo_fim = angulo_inicio + angulo
        if quantidade_segmentos == 1:
            caminho = (
                "M 100 100 L 100 0 A 100 100 0 1 1 100 200 "
                "A 100 100 0 1 1 100 0 Z"
            )
        else:
            inicio_x = 100 + 100 * math.cos(math.radians(angulo_inicio))
            inicio_y = 100 + 100 * math.sin(math.radians(angulo_inicio))
            fim_x = 100 + 100 * math.cos(math.radians(angulo_fim))
            fim_y = 100 + 100 * math.sin(math.radians(angulo_fim))
            arco_longo = 1 if angulo > 180 else 0
            caminho = (
                f"M 100 100 L {inicio_x:.3f} {inicio_y:.3f} "
                f"A 100 100 0 {arco_longo} 1 {fim_x:.3f} {fim_y:.3f} Z"
            )
        segmentos.append(
            {
                "rotulo": rotulo,
                "valor": valor,
                "percentual": round(valor / total * 100, 1),
                "cor": cores[indice % len(cores)],
                "caminho": caminho,
            }
        )
        angulo_inicio = angulo_fim
    return segmentos


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
    crises_abertas_fechadas = [
        ("Abertas", metricas["crises"]["abertas_atualmente"]),
        ("Fechadas", metricas["crises"]["fechadas_historico"]),
    ]
    rdms_abertas_fechadas = [
        ("Abertas", metricas["rdms"]["abertas_historico"]),
        ("Fechadas", metricas["rdms"]["fechadas_historico"]),
    ]
    html = render_template(
        "pdf/relatorio_ia.html",
        ano=ano,
        relatorio_formatado=_formatar_relatorio(relatorio),
        metricas=metricas,
        serie_crises=[
            (mes, metricas["crises"]["criadas_no_ano_por_mes"][str(indice)])
            for indice, mes in enumerate(meses, start=1)
        ],
        serie_rdms=[
            (mes, metricas["rdms"]["criadas_no_ano_por_mes"][str(indice)])
            for indice, mes in enumerate(meses, start=1)
        ],
        serie_crises_status=crises_por_status,
        serie_crises_criticidade=crises_por_criticidade,
        serie_rdms_status=rdms_por_status,
        pizza_crises=_segmentos_pizza(crises_abertas_fechadas),
        pizza_rdms=_segmentos_pizza(rdms_abertas_fechadas),
        emitido_em=agora().astimezone(fuso).strftime("%d/%m/%Y às %H:%M"),
    )
    from weasyprint import HTML

    return HTML(string=html, base_url=str(Path(current_app.root_path))).write_pdf()
