from datetime import datetime, timedelta

from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import func

from ..extensions import db
from ..models import RDM, Atividade, Crise, Equipe, StatusRDM

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
