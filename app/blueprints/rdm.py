from datetime import datetime

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, or_

from ..extensions import db
from ..models import (
    RDM,
    Atividade,
    CatalogoAtividade,
    Criticidade,
    Equipe,
    LogRDM,
    ResultadoRDM,
    StatusAtividade,
    StatusRDM,
    User,
    agora,
)
from ..security import gestor_requerido, normalizar_emails
from ..services.email_service import (
    TEXTO_PADRAO_RDM,
    enviar_encerramento,
    enviar_rdm,
    montar_email_encerramento,
    montar_email_rdm,
    texto_padrao_encerramento,
)
from ..services.pdf_service import gerar_pdf_rdm

rdm_bp = Blueprint("rdm", __name__)


# --------------------------------------------------------------- utilidades
def _log(rdm, acao, descricao=""):
    db.session.add(
        LogRDM(
            rdm_id=rdm.id,
            usuario_id=current_user.id,
            usuario_nome=current_user.nome,
            acao=acao,
            descricao=descricao,
        )
    )


def _proximo_numero() -> str:
    ano = datetime.now().year
    prefixo = f"RDM-{ano}-"
    ultimo = (
        db.session.query(func.max(RDM.numero))
        .filter(RDM.numero.like(f"{prefixo}%"))
        .scalar()
    )
    sequencia = int(ultimo.rsplit("-", 1)[-1]) + 1 if ultimo else 1
    return f"{prefixo}{sequencia:03d}"


def _enum_ou_none(enum_cls, valor):
    try:
        return enum_cls[valor] if valor else None
    except KeyError:
        return None


def _dt(valor):
    if not valor:
        return None
    for formato in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(valor, formato)
        except ValueError:
            continue
    return None


def _minutos(campo_h: str, campo_min: str) -> int:
    """Combina os campos de horas e minutos em um total de minutos."""
    f = request.form
    horas = (f.get(campo_h) or "").strip()
    minutos = (f.get(campo_min) or "").strip()
    total = 0
    if horas.isdigit():
        total += int(horas) * 60
    if minutos.isdigit():
        total += int(minutos)
    return total


def _minutos_lista(horas_lista, minutos_lista, i: int) -> int:
    h = (horas_lista[i] if i < len(horas_lista) else "").strip()
    m = (minutos_lista[i] if i < len(minutos_lista) else "").strip()
    total = 0
    if h.isdigit():
        total += int(h) * 60
    if m.isdigit():
        total += int(m)
    return total


def _carregar_ou_404(rdm_id) -> RDM:
    rdm = db.session.get(RDM, rdm_id)
    if not rdm:
        abort(404)
    return rdm


def _pode_editar(rdm: RDM) -> bool:
    if not rdm.editavel:
        return False
    return current_user.is_gestor or rdm.solicitante_id == current_user.id


def _aplicar_formulario(rdm: RDM) -> list[str]:
    """Lê o formulário, valida e aplica na RDM. Devolve lista de erros."""
    f = request.form
    erros = []

    rdm.titulo = (f.get("titulo") or "").strip()
    if len(rdm.titulo) < 5:
        erros.append("Informe um título com pelo menos 5 caracteres.")

    solicitante_id = f.get("solicitante_id")
    if solicitante_id and solicitante_id.isdigit():
        rdm.solicitante_id = int(solicitante_id)
    elif not rdm.solicitante_id:
        rdm.solicitante_id = current_user.id

    rdm.sistema = (f.get("sistema") or "").strip()
    rdm.modulo = (f.get("modulo") or "").strip()
    rdm.negocio = (f.get("negocio") or "").strip()
    rdm.ambiente = (f.get("ambiente") or "").strip()

    revisor_id = f.get("revisor_id")
    rdm.revisor_id = int(revisor_id) if revisor_id and revisor_id.isdigit() else None

    rdm.objetivo = (f.get("objetivo") or "").strip()
    if len(rdm.objetivo) < 10:
        erros.append("Descreva o objetivo da mudança.")

    rdm.ativos_envolvidos = (f.get("ativos_envolvidos") or "").strip()
    rdm.sistemas_impactados = (f.get("sistemas_impactados") or "").strip()
    rdm.riscos = (f.get("riscos") or "").strip()
    rdm.criticidade = _enum_ou_none(Criticidade, f.get("criticidade")) or Criticidade.MEDIA
    rdm.indisponibilidade = f.get("indisponibilidade") == "on"

    rdm.tipo_manutencao = (f.get("tipo_manutencao") or "").strip()
    rdm.inicio_previsto = _dt(f.get("inicio_previsto"))
    rdm.fim_previsto = _dt(f.get("fim_previsto"))
    rdm.motivo = (f.get("motivo") or "").strip()

    if rdm.inicio_previsto and rdm.fim_previsto and rdm.fim_previsto <= rdm.inicio_previsto:
        erros.append("O fim da janela precisa ser posterior ao início.")

    rdm.plano_rollback = (f.get("plano_rollback") or "").strip()
    if not rdm.plano_rollback:
        erros.append("O plano de rollback é obrigatório.")
    rdm.tempo_rollback_min = _minutos("tempo_rollback_h", "tempo_rollback_m") or None

    rdm.emergencial = f.get("emergencial") == "on"

    # O autorizador pode vir do cadastro de pessoas ou ser digitado (externo).
    autorizador_id = f.get("autorizador_id")
    if autorizador_id and autorizador_id.isdigit():
        pessoa = db.session.get(User, int(autorizador_id))
        if pessoa:
            rdm.autorizado_por = pessoa.nome_completo
            rdm.autorizado_cargo = pessoa.cargo or ""
            rdm.autorizado_email = pessoa.email
            rdm.autorizado_telefone = pessoa.telefone or ""
    else:
        rdm.autorizado_por = (f.get("autorizado_por") or "").strip()
        rdm.autorizado_cargo = (f.get("autorizado_cargo") or "").strip()
        rdm.autorizado_email = (f.get("autorizado_email") or "").strip()
        rdm.autorizado_telefone = (f.get("autorizado_telefone") or "").strip()

    rdm.departamento = (f.get("departamento") or "").strip()

    return erros


def _aplicar_atividades(rdm: RDM) -> list[str]:
    """Substitui o plano de trabalho pelas linhas enviadas no formulário."""
    f = request.form
    equipes = f.getlist("atv_equipe")
    descricoes = f.getlist("atv_descricao")
    analistas = f.getlist("atv_analista_id")
    nomes = f.getlist("atv_analista_nome")
    duracoes_h = f.getlist("atv_duracao_h")
    duracoes_m = f.getlist("atv_duracao_m")
    rollbacks = f.getlist("atv_rollback")

    novas, erros_atividade = [], []
    for i, equipe_nome in enumerate(equipes):
        descricao = (descricoes[i] if i < len(descricoes) else "").strip()
        equipe = _enum_ou_none(Equipe, equipe_nome)
        if not descricao or not equipe:
            continue

        analista_id = analistas[i] if i < len(analistas) else ""
        analista_nome = (nomes[i] if i < len(nomes) else "").strip()

        # Documento de auditoria: toda atividade precisa de um responsável.
        if not analista_id.isdigit() and not analista_nome:
            erros_atividade.append(
                f"Informe o analista responsável pela atividade "
                f"\u201c{descricao[:60]}\u201d ({equipe.value})."
            )

        novas.append(
            Atividade(
                equipe=equipe,
                ordem=len(novas) + 1,
                descricao=descricao,
                analista_id=int(analista_id) if analista_id.isdigit() else None,
                analista_nome=analista_nome or None,
                duracao_min=_minutos_lista(duracoes_h, duracoes_m, i),
                rollback=(rollbacks[i] if i < len(rollbacks) else "").strip() or None,
            )
        )

    if not novas:
        return ["Inclua pelo menos uma atividade no plano de trabalho."]
    if erros_atividade:
        return erros_atividade

    rdm.atividades.clear()
    rdm.atividades.extend(novas)
    return []


def _contexto_formulario():
    pessoas = db.session.query(User).filter_by(ativo=True).order_by(User.nome).all()
    return {
        "usuarios": pessoas,
        # Quem pode autorizar: gestores, administradores e pessoas de referência
        # cadastradas com cargo (autoridades que assinam sem usar o sistema).
        "autorizadores": [
            u for u in pessoas if u.is_gestor or (u.somente_referencia and u.cargo)
        ],
        "catalogo": db.session.query(CatalogoAtividade)
        .filter_by(ativo=True)
        .order_by(CatalogoAtividade.equipe, CatalogoAtividade.descricao)
        .all(),
        "criticidades": list(Criticidade),
        "equipes": list(Equipe),
    }


# -------------------------------------------------------------------- rotas
@rdm_bp.route("/")
@login_required
def lista():
    busca = (request.args.get("q") or "").strip()
    status = request.args.get("status") or ""
    pagina = request.args.get("pagina", 1, type=int)

    consulta = db.session.query(RDM)
    if busca:
        termo = f"%{busca}%"
        consulta = consulta.filter(
            or_(RDM.titulo.ilike(termo), RDM.numero.ilike(termo), RDM.sistema.ilike(termo))
        )
    if status:
        membro = _enum_ou_none(StatusRDM, status)
        if membro:
            consulta = consulta.filter(RDM.status == membro)

    paginacao = db.paginate(
        consulta.order_by(RDM.criado_em.desc()), page=pagina, per_page=15, error_out=False
    )
    return render_template(
        "rdm/lista.html",
        paginacao=paginacao,
        busca=busca,
        status_atual=status,
        status_opcoes=list(StatusRDM),
    )


@rdm_bp.route("/nova", methods=["GET", "POST"])
@login_required
def nova():
    if request.method == "GET":
        return render_template(
            "rdm/form.html", rdm=None, modo="nova", **_contexto_formulario()
        )

    rdm = RDM(solicitante_id=current_user.id, status=StatusRDM.RASCUNHO)
    erros = _aplicar_formulario(rdm) + _aplicar_atividades(rdm)

    if erros:
        for e in erros:
            flash(e, "danger")
        return (
            render_template(
                "rdm/form.html", rdm=rdm, modo="nova", **_contexto_formulario()
            ),
            400,
        )

    rdm.numero = _proximo_numero()
    rdm.status = StatusRDM.ABERTA
    db.session.add(rdm)
    db.session.flush()
    _log(rdm, "CRIACAO", f"RDM criada com {len(rdm.atividades)} atividades.")
    db.session.commit()

    flash(f"{rdm.identificador} criada.", "success")
    return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))


@rdm_bp.route("/<int:rdm_id>")
@login_required
def detalhe(rdm_id):
    rdm = _carregar_ou_404(rdm_id)
    return render_template(
        "rdm/detalhe.html",
        rdm=rdm,
        grupos=rdm.atividades_por_equipe(),
        pode_editar=_pode_editar(rdm),
        status_opcoes=list(StatusRDM),
        status_atividade=list(StatusAtividade),
    )


@rdm_bp.route("/<int:rdm_id>/editar", methods=["GET", "POST"])
@login_required
def editar(rdm_id):
    rdm = _carregar_ou_404(rdm_id)
    if not _pode_editar(rdm):
        abort(403)

    if request.method == "GET":
        return render_template(
            "rdm/form.html", rdm=rdm, modo="editar", **_contexto_formulario()
        )

    erros = _aplicar_formulario(rdm) + _aplicar_atividades(rdm)
    if erros:
        for e in erros:
            flash(e, "danger")
        return (
            render_template(
                "rdm/form.html", rdm=rdm, modo="editar", **_contexto_formulario()
            ),
            400,
        )

    _log(rdm, "EDICAO", "Dados e plano de trabalho atualizados.")
    db.session.commit()
    flash("RDM atualizada.", "success")
    return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))


@rdm_bp.route("/<int:rdm_id>/status", methods=["POST"])
@login_required
@gestor_requerido
def alterar_status(rdm_id):
    rdm = _carregar_ou_404(rdm_id)
    novo = _enum_ou_none(StatusRDM, request.form.get("status"))
    if not novo:
        flash("Status inválido.", "danger")
        return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))

    anterior = rdm.status.value
    rdm.status = novo
    if novo == StatusRDM.EXECUTADA and not rdm.fim_real:
        rdm.fim_real = datetime.now()
    _log(rdm, "STATUS", f"{anterior} → {novo.value}")
    db.session.commit()

    flash(f"Status alterado para {novo.value}.", "success")
    return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))


@rdm_bp.route("/<int:rdm_id>/atividade/<int:atividade_id>/status", methods=["POST"])
@login_required
def status_atividade(rdm_id, atividade_id):
    rdm = _carregar_ou_404(rdm_id)
    atividade = db.session.get(Atividade, atividade_id)
    if not atividade or atividade.rdm_id != rdm.id:
        abort(404)

    novo = _enum_ou_none(StatusAtividade, request.form.get("status"))
    if not novo:
        abort(400)

    atividade.status = novo
    atividade.observacao = (request.form.get("observacao") or "").strip() or None
    _log(rdm, "ATIVIDADE", f"#{atividade.ordem} {atividade.equipe.value}: {novo.value}")
    db.session.commit()

    flash("Atividade atualizada.", "success")
    return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))


@rdm_bp.route("/<int:rdm_id>/andamento", methods=["POST"])
@login_required
def andamento(rdm_id):
    rdm = _carregar_ou_404(rdm_id)
    texto = (request.form.get("texto") or "").strip()
    if not texto:
        flash("Escreva a atualização antes de registrar.", "danger")
        return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))

    _log(rdm, "ANDAMENTO", texto)
    db.session.commit()
    flash("Andamento registrado.", "success")
    return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))


# ----------------------------------------------------------------- e-mail
def _destinatarios_sugeridos(rdm) -> str:
    sugeridos = [a.analista.email for a in rdm.atividades if a.analista]
    if rdm.revisor:
        sugeridos.append(rdm.revisor.email)
    if rdm.solicitante:
        sugeridos.append(rdm.solicitante.email)
    if rdm.autorizado_email:
        sugeridos.append(rdm.autorizado_email)
    return ", ".join(normalizar_emails(*sugeridos))


def _tela_email(rdm, tipo, introducao, observacao, destinatarios, codigo=200):
    """Renderiza a tela de e-mail já com o formulário preenchido."""
    if tipo == "encerramento":
        assunto, html, _ = montar_email_encerramento(rdm, introducao, observacao, preview=True)
        padrao = texto_padrao_encerramento(rdm.resultado)
    else:
        assunto, html, _ = montar_email_rdm(rdm, introducao, observacao, preview=True)
        padrao = TEXTO_PADRAO_RDM

    return (
        render_template(
            "rdm/email.html",
            rdm=rdm,
            tipo=tipo,
            assunto=assunto,
            corpo_html=html,
            introducao=introducao,
            observacao=observacao,
            destinatarios=destinatarios,
            texto_padrao=padrao,
        ),
        codigo,
    )


@rdm_bp.route("/<int:rdm_id>/email", methods=["GET", "POST"])
@login_required
def preview_email(rdm_id):
    """Mostra exatamente o e-mail que será enviado, antes de disparar."""
    rdm = _carregar_ou_404(rdm_id)
    if not current_user.pode_disparar_email:
        abort(403)

    tipo = request.values.get("tipo") or "abertura"
    if tipo == "encerramento" and not rdm.encerrada:
        flash("Registre o encerramento da RDM antes de comunicar o fechamento.", "warning")
        return redirect(url_for("rdm.encerrar", rdm_id=rdm.id))

    padrao = texto_padrao_encerramento(rdm.resultado) if tipo == "encerramento" else TEXTO_PADRAO_RDM
    introducao = request.form.get("introducao") or padrao
    observacao = request.form.get("observacao") or ""
    destinatarios = request.form.get("destinatarios") or _destinatarios_sugeridos(rdm)

    if request.method == "POST":
        flash("Pré-visualização atualizada.", "info")

    return _tela_email(rdm, tipo, introducao, observacao, destinatarios)


@rdm_bp.route("/<int:rdm_id>/email/enviar", methods=["POST"])
@login_required
def enviar_email(rdm_id):
    rdm = _carregar_ou_404(rdm_id)
    if not current_user.pode_disparar_email:
        abort(403)

    tipo = request.form.get("tipo") or "abertura"
    encerramento = tipo == "encerramento"
    if encerramento and not rdm.encerrada:
        flash("Registre o encerramento da RDM antes de comunicar o fechamento.", "warning")
        return redirect(url_for("rdm.encerrar", rdm_id=rdm.id))

    padrao = texto_padrao_encerramento(rdm.resultado) if encerramento else TEXTO_PADRAO_RDM
    introducao = request.form.get("introducao") or padrao
    observacao = request.form.get("observacao") or ""
    texto_destinatarios = request.form.get("destinatarios") or ""
    destinatarios = normalizar_emails(texto_destinatarios)

    # Em qualquer falha, a tela volta preenchida — o texto digitado não se perde.
    if not destinatarios:
        flash("Informe pelo menos um destinatário válido.", "danger")
        return _tela_email(rdm, tipo, introducao, observacao, texto_destinatarios, 400)

    anexo = None
    if request.form.get("anexar_pdf") == "on":
        try:
            anexo = str(gerar_pdf_rdm(rdm))
        except Exception as exc:  # noqa: BLE001
            flash(f"O PDF não pôde ser gerado, o e-mail seguiu sem anexo. ({exc})", "warning")

    try:
        despachar = enviar_encerramento if encerramento else enviar_rdm
        (ok, erro), todos = despachar(rdm, destinatarios, introducao, observacao, anexo)
    except Exception as exc:  # noqa: BLE001
        _log(rdm, "EMAIL_FALHA", str(exc)[:400])
        db.session.commit()
        flash(f"O e-mail não foi enviado: {exc}", "danger")
        return _tela_email(rdm, tipo, introducao, observacao, texto_destinatarios, 400)

    # O envio é síncrono: se o servidor recusou, o usuário precisa saber agora.
    if not ok:
        _log(rdm, "EMAIL_FALHA", (erro or "")[:400])
        db.session.commit()
        flash(f"O e-mail não foi enviado: {erro}", "danger")
        return _tela_email(rdm, tipo, introducao, observacao, texto_destinatarios, 400)

    if encerramento:
        rdm.encerramento_enviado_em = agora()
        _log(rdm, "EMAIL_ENCERRAMENTO", "Enviado para: " + ", ".join(todos))
    else:
        rdm.enviado_em = agora()
        _log(rdm, "EMAIL", "Enviado para: " + ", ".join(todos))
    db.session.commit()

    flash(f"E-mail enviado para {len(todos)} destinatário(s).", "success")
    return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))


# ----------------------------------------------------------- encerramento
@rdm_bp.route("/<int:rdm_id>/encerrar", methods=["GET", "POST"])
@login_required
@gestor_requerido
def encerrar(rdm_id):
    """Registra o desfecho da janela: horas reais, resultado e relato."""
    rdm = _carregar_ou_404(rdm_id)

    if request.method == "GET":
        return render_template(
            "rdm/encerrar.html",
            rdm=rdm,
            resultados=list(ResultadoRDM),
            status_atividade=list(StatusAtividade),
        )

    resultado = _enum_ou_none(ResultadoRDM, request.form.get("resultado"))
    inicio_real = _dt(request.form.get("inicio_real"))
    fim_real = _dt(request.form.get("fim_real"))
    relato = (request.form.get("relato_encerramento") or "").strip()

    erros = []
    if not resultado:
        erros.append("Selecione o resultado da janela.")
    if not inicio_real or not fim_real:
        erros.append("Informe o início e o fim reais da execução.")
    elif fim_real <= inicio_real:
        erros.append("O fim real precisa ser posterior ao início real.")
    if len(relato) < 10:
        erros.append("Descreva o que aconteceu durante a janela.")

    if erros:
        for e in erros:
            flash(e, "danger")
        return (
            render_template(
                "rdm/encerrar.html",
                rdm=rdm,
                resultados=list(ResultadoRDM),
                status_atividade=list(StatusAtividade),
            ),
            400,
        )

    # Status de cada atividade, informado no mesmo formulário
    for atividade in rdm.atividades:
        novo = _enum_ou_none(StatusAtividade, request.form.get(f"atividade_{atividade.id}"))
        if novo:
            atividade.status = novo
        observacao = (request.form.get(f"observacao_{atividade.id}") or "").strip()
        atividade.observacao = observacao or None

    rdm.resultado = resultado
    rdm.inicio_real = inicio_real
    rdm.fim_real = fim_real
    rdm.relato_encerramento = relato
    rdm.rollback_acionado = (
        request.form.get("rollback_acionado") == "on" or resultado == ResultadoRDM.ROLLBACK
    )
    rdm.encerrado_em = agora()
    rdm.encerrado_por_id = current_user.id
    rdm.status = (
        StatusRDM.CANCELADA if resultado == ResultadoRDM.NAO_EXECUTADA else StatusRDM.EXECUTADA
    )

    _log(
        rdm,
        "ENCERRAMENTO",
        f"{resultado.value} · duração real {rdm.duracao_real_formatada} "
        f"({rdm.desvio_formatado})",
    )
    db.session.commit()

    flash("Encerramento registrado. Revise o comunicado antes de enviar.", "success")
    return redirect(url_for("rdm.preview_email", rdm_id=rdm.id, tipo="encerramento"))


# -------------------------------------------------------------------- PDF
@rdm_bp.route("/<int:rdm_id>/pdf")
@login_required
def pdf(rdm_id):
    rdm = _carregar_ou_404(rdm_id)
    try:
        caminho = gerar_pdf_rdm(rdm)
    except Exception as exc:  # noqa: BLE001
        flash(f"Não foi possível gerar o PDF: {exc}", "danger")
        return redirect(url_for("rdm.detalhe", rdm_id=rdm.id))
    # Caminho montado pelo servidor a partir do ID — nunca vem do banco.
    return send_file(caminho, mimetype="application/pdf", download_name=caminho.name)


# ---------------------------------------------------------------- exclusão
@rdm_bp.route("/<int:rdm_id>/excluir", methods=["POST"])
@login_required
@gestor_requerido
def excluir(rdm_id):
    rdm = _carregar_ou_404(rdm_id)
    identificador = rdm.identificador
    db.session.delete(rdm)
    db.session.commit()
    flash(f"{identificador} excluída.", "success")
    return redirect(url_for("rdm.lista"))
