from datetime import datetime, timedelta

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import extract, func

from ..extensions import db
from ..models import RDM, Atividade, Crise, Equipe, StatusRDM, User

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
    """Quantidade de RDMs por ano, por mês e por analista responsável."""
    anos = [
        int(a)
        for (a,) in db.session.query(extract("year", RDM.criado_em))
        .distinct()
        .order_by(extract("year", RDM.criado_em).desc())
        .all()
        if a
    ]
    ano_atual = datetime.now().year
    if ano_atual not in anos:
        anos.insert(0, ano_atual)

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

    return render_template(
        "painel/indicadores.html",
        anos=anos,
        ano=ano,
        serie_anos=serie_anos,
        serie_meses=serie_meses,
        analistas=analistas,
        por_equipe=por_equipe,
        por_status=por_status,
        equipes=list(Equipe),
        status_opcoes=list(StatusRDM),
        total_ano=sum(contagem_mes.values()),
        total_geral=sum(por_ano.values()),
    )