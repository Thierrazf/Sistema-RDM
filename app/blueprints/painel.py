from datetime import datetime, timedelta
from io import BytesIO

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import login_required
from sqlalchemy import extract, func

from ..extensions import db, limiter
from ..models import (
    RDM,
    Atividade,
    ConfiguracaoIA,
    Crise,
    Criticidade,
    Equipe,
    StatusRDM,
    User,
)
from ..services.pdf_service import gerar_pdf_relatorio_ia
from ..services.relatorio_ia_service import (
    ErroConfiguracaoIA,
    ErroRelatorioIA,
    gerar_relatorio,
)

painel_bp = Blueprint("painel", __name__)


@painel_bp.route("/")
@login_required
def inicio():
    agora = datetime.now()
    limite = agora + timedelta(days=14)

    proximas = (
        db.session.query(RDM)
        .filter(
            RDM.inicio_previsto.isnot(None),
            RDM.inicio_previsto >= agora,
            RDM.inicio_previsto <= limite,
            RDM.status.notin_([StatusRDM.CANCELADA, StatusRDM.FECHADA]),
        )
        .order_by(RDM.inicio_previsto)
        .limit(6)
        .all()
    )

    por_status = dict(
        db.session.query(RDM.status, func.count(RDM.id)).group_by(RDM.status).all()
    )

    carga_equipes = dict(
        db.session.query(Atividade.equipe, func.count(Atividade.id))
        .join(RDM, RDM.id == Atividade.rdm_id)
        .filter(RDM.status.notin_([StatusRDM.CANCELADA, StatusRDM.FECHADA]))
        .group_by(Atividade.equipe)
        .all()
    )

    recentes = db.session.query(RDM).order_by(RDM.criado_em.desc()).limit(8).all()
    crises_abertas = db.session.query(Crise).filter(Crise.status != "Fechada").count()

    return render_template(
        "painel/inicio.html",
        proximas=proximas,
        por_status=por_status,
        carga_equipes=carga_equipes,
        equipes=list(Equipe),
        recentes=recentes,
        crises_abertas=crises_abertas,
        total_rdm=db.session.query(func.count(RDM.id)).scalar() or 0,
    )


MESES = [
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
]


@painel_bp.route("/indicadores")
@login_required
def indicadores():
    """Exibe métricas de RDMs e crises por período e situação."""
    anos_rdm = [
        int(a)
        for (a,) in db.session.query(extract("year", RDM.criado_em))
        .distinct()
        .order_by(extract("year", RDM.criado_em).desc())
        .all()
        if a
    ]
    anos_crise = [
        int(a)
        for (a,) in db.session.query(extract("year", Crise.criado_em))
        .distinct()
        .order_by(extract("year", Crise.criado_em).desc())
        .all()
        if a
    ]
    ano_atual = datetime.now().year
    anos = sorted(set(anos_rdm + anos_crise + [ano_atual]), reverse=True)

    ano = request.args.get("ano", type=int) or anos[0]

    por_ano = {
        int(a): total
        for a, total in db.session.query(
            extract("year", RDM.criado_em), func.count(RDM.id)
        )
        .group_by(extract("year", RDM.criado_em))
        .all()
        if a
    }
    serie_anos = [(a, por_ano.get(a, 0)) for a in sorted(por_ano)]

    contagem_mes = {
        int(m): total
        for m, total in db.session.query(
            extract("month", RDM.criado_em), func.count(RDM.id)
        )
        .filter(extract("year", RDM.criado_em) == ano)
        .group_by(extract("month", RDM.criado_em))
        .all()
        if m
    }
    serie_meses = [(MESES[m - 1], contagem_mes.get(m, 0)) for m in range(1, 13)]

    # Conta RDMs distintas em que o analista tem ao menos uma atividade, e não
    # o total de atividades — interessa em quantas mudanças a pessoa atuou.
    por_analista = (
        db.session.query(
            User.nome,
            User.equipe,
            func.count(func.distinct(Atividade.rdm_id)).label("total"),
        )
        .join(Atividade, Atividade.analista_id == User.id)
        .join(RDM, RDM.id == Atividade.rdm_id)
        .filter(extract("year", RDM.criado_em) == ano)
        .group_by(User.id)
        .order_by(func.count(func.distinct(Atividade.rdm_id)).desc())
        .all()
    )

    por_nome_livre = (
        db.session.query(
            Atividade.analista_nome,
            func.count(func.distinct(Atividade.rdm_id)).label("total"),
        )
        .join(RDM, RDM.id == Atividade.rdm_id)
        .filter(
            Atividade.analista_id.is_(None),
            Atividade.analista_nome.isnot(None),
            extract("year", RDM.criado_em) == ano,
        )
        .group_by(Atividade.analista_nome)
        .all()
    )

    analistas = [
        {"nome": nome, "equipe": equipe, "total": total}
        for nome, equipe, total in por_analista
    ] + [
        {"nome": nome, "equipe": None, "total": total}
        for nome, total in por_nome_livre
    ]
    analistas.sort(key=lambda a: a["total"], reverse=True)

    por_equipe = {
        equipe: total
        for equipe, total in db.session.query(
            Atividade.equipe, func.count(func.distinct(Atividade.rdm_id))
        )
        .join(RDM, RDM.id == Atividade.rdm_id)
        .filter(extract("year", RDM.criado_em) == ano)
        .group_by(Atividade.equipe)
        .all()
    }

    por_status = {
        status: total
        for status, total in db.session.query(RDM.status, func.count(RDM.id))
        .filter(extract("year", RDM.criado_em) == ano)
        .group_by(RDM.status)
        .all()
    }

    por_ano_crise = {
        int(a): total
        for a, total in db.session.query(
            extract("year", Crise.criado_em), func.count(Crise.id)
        )
        .group_by(extract("year", Crise.criado_em))
        .all()
        if a
    }
    serie_anos_crise = [(a, por_ano_crise.get(a, 0)) for a in sorted(por_ano_crise)]

    contagem_mes_crise = {
        int(m): total
        for m, total in db.session.query(
            extract("month", Crise.criado_em), func.count(Crise.id)
        )
        .filter(extract("year", Crise.criado_em) == ano)
        .group_by(extract("month", Crise.criado_em))
        .all()
        if m
    }
    serie_meses_crise = [
        (MESES[m - 1], contagem_mes_crise.get(m, 0)) for m in range(1, 13)
    ]

    por_status_crise = dict(
        db.session.query(Crise.status, func.count(Crise.id))
        .filter(extract("year", Crise.criado_em) == ano)
        .group_by(Crise.status)
        .all()
    )

    por_criticidade_crise = dict(
        db.session.query(Crise.criticidade, func.count(Crise.id))
        .filter(extract("year", Crise.criado_em) == ano)
        .group_by(Crise.criticidade)
        .all()
    )

    return render_template(
        "painel/indicadores.html",
        anos=anos,
        ano=ano,
        serie_anos=serie_anos,
        serie_meses=serie_meses,
        analistas=analistas,
        por_equipe=por_equipe,
        por_status=por_status,
        serie_anos_crise=serie_anos_crise,
        serie_meses_crise=serie_meses_crise,
        por_status_crise=por_status_crise,
        por_criticidade_crise=por_criticidade_crise,
        criticidades=list(Criticidade),
        equipes=list(Equipe),
        status_opcoes=list(StatusRDM),
        total_ano=sum(contagem_mes.values()),
        total_geral=sum(por_ano.values()),
        total_crises_ano=sum(contagem_mes_crise.values()),
        total_crises_geral=sum(por_ano_crise.values()),
    )


@painel_bp.route("/indicadores/relatorio-ia", methods=["POST"])
@login_required
@limiter.limit("5 per hour")
def gerar_relatorio_indicadores():
    ano = request.form.get("ano", type=int) or datetime.now().year
    configuracao = db.session.get(ConfiguracaoIA, 1)
    if not configuracao or not configuracao.api_key_cifrada:
        flash("A integração de IA ainda não foi configurada pelo administrador.", "warning")
        return redirect(url_for("painel.indicadores", ano=ano))

    crises_por_status_aberto = dict(
        db.session.query(Crise.status, func.count(Crise.id))
        .filter(Crise.status != "Fechada")
        .group_by(Crise.status)
        .all()
    )
    crises_abertas_por_criticidade = {
        criticidade.value if criticidade else "Não informada": total
        for criticidade, total in db.session.query(Crise.criticidade, func.count(Crise.id))
        .filter(Crise.status != "Fechada")
        .group_by(Crise.criticidade)
        .all()
    }
    crises_por_mes = {
        int(mes): total
        for mes, total in db.session.query(
            extract("month", Crise.criado_em), func.count(Crise.id)
        )
        .filter(extract("year", Crise.criado_em) == ano)
        .group_by(extract("month", Crise.criado_em))
        .all()
        if mes
    }
    rdms_por_mes = {
        int(mes): total
        for mes, total in db.session.query(
            extract("month", RDM.criado_em), func.count(RDM.id)
        )
        .filter(extract("year", RDM.criado_em) == ano)
        .group_by(extract("month", RDM.criado_em))
        .all()
        if mes
    }
    rdms_por_status = {
        status.value: total
        for status, total in db.session.query(RDM.status, func.count(RDM.id))
        .filter(extract("year", RDM.criado_em) == ano)
        .group_by(RDM.status)
        .all()
    }
    metricas = {
        "ano_analisado": ano,
        "crises": {
            "total_historico": db.session.query(func.count(Crise.id)).scalar() or 0,
            "abertas_atualmente": sum(crises_por_status_aberto.values()),
            "abertas_por_status": crises_por_status_aberto,
            "abertas_por_criticidade": crises_abertas_por_criticidade,
            "criadas_no_ano_por_mes": {
                str(mes): crises_por_mes.get(mes, 0) for mes in range(1, 13)
            },
        },
        "rdms": {
            "total_historico": db.session.query(func.count(RDM.id)).scalar() or 0,
            "criadas_no_ano_por_mes": {
                str(mes): rdms_por_mes.get(mes, 0) for mes in range(1, 13)
            },
            "situacao_no_ano": rdms_por_status,
        },
    }

    try:
        relatorio = gerar_relatorio(configuracao, metricas)
    except (ErroConfiguracaoIA, ErroRelatorioIA) as exc:
        flash(str(exc), "danger")
        return redirect(url_for("painel.indicadores", ano=ano))

    try:
        pdf = gerar_pdf_relatorio_ia(ano, relatorio, metricas)
    except Exception as exc:  # noqa: BLE001
        flash(f"A análise foi gerada, mas não foi possível criar o PDF: {exc}", "danger")
        return redirect(url_for("painel.indicadores", ano=ano))

    return send_file(
        BytesIO(pdf),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"relatorio-gerencial-{ano}.pdf",
    )
