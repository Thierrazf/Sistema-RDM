from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from ..extensions import db
from ..models import Crise, Criticidade, LogCrise, agora
from ..security import gestor_requerido, normalizar_emails
from ..services.email_service import enviar_crise
from ..services.pdf_service import gerar_pdf_crise

crise_bp = Blueprint("crise", __name__)


def _enum(cls, valor):
    try:
        return cls[valor] if valor else None
    except KeyError:
        return None


def _carregar(crise_id) -> Crise:
    crise = db.session.get(Crise, crise_id)
    if not crise:
        abort(404)
    return crise


def _log(crise, descricao):
    db.session.add(
        LogCrise(crise_id=crise.id, usuario_nome=current_user.nome, descricao=descricao)
    )


@crise_bp.route("/")
@login_required
def lista():
    pagina = request.args.get("pagina", 1, type=int)
    paginacao = db.paginate(
        db.session.query(Crise).order_by(Crise.criado_em.desc()),
        page=pagina,
        per_page=15,
        error_out=False,
    )
    return render_template("crise/lista.html", paginacao=paginacao)


@crise_bp.route("/nova", methods=["GET", "POST"])
@login_required
def nova():
    if request.method == "GET":
        return render_template("crise/form.html", criticidades=list(Criticidade))

    titulo = (request.form.get("titulo") or "").strip()
    problema = (request.form.get("problema") or "").strip()
    if len(titulo) < 5 or len(problema) < 10:
        flash("Informe um título e a descrição do problema.", "danger")
        return render_template("crise/form.html", criticidades=list(Criticidade)), 400

    crise = Crise(
        titulo=titulo,
        problema=problema,
        local=(request.form.get("local") or "").strip(),
        origem=(request.form.get("origem") or "").strip(),
        criticidade=_enum(Criticidade, request.form.get("criticidade")) or Criticidade.ALTA,
        causa_raiz=(request.form.get("causa_raiz") or "").strip(),
        solucao=(request.form.get("solucao") or "").strip(),
        aberta_por_id=current_user.id,
        status="Aberta",
    )
    db.session.add(crise)
    db.session.flush()
    _log(crise, "Crise aberta.")
    db.session.commit()

    flash(f"{crise.identificador} aberta.", "success")
    return redirect(url_for("crise.detalhe", crise_id=crise.id))


@crise_bp.route("/<int:crise_id>")
@login_required
def detalhe(crise_id):
    crise = _carregar(crise_id)
    return render_template("crise/detalhe.html", crise=crise)


@crise_bp.route("/<int:crise_id>/andamento", methods=["POST"])
@login_required
def andamento(crise_id):
    crise = _carregar(crise_id)
    texto = (request.form.get("texto") or "").strip()
    if not texto:
        flash("Escreva a atualização antes de registrar.", "danger")
        return redirect(url_for("crise.detalhe", crise_id=crise.id))

    _log(crise, texto)

    if request.form.get("enviar_email") == "on":
        if not current_user.pode_disparar_email:
            db.session.commit()
            flash("Andamento registrado. Você não tem permissão para enviar e-mails.", "warning")
            return redirect(url_for("crise.detalhe", crise_id=crise.id))

        destinatarios = normalizar_emails(request.form.get("destinatarios"))
        if destinatarios:
            try:
                anexo = str(gerar_pdf_crise(crise))
                enviar_crise(crise, destinatarios, anexo)
                _log(crise, "Comunicado enviado para: " + ", ".join(destinatarios))
            except Exception as exc:  # noqa: BLE001
                _log(crise, f"Falha no envio do comunicado: {exc}")
                flash(f"O comunicado não foi enviado: {exc}", "danger")

    db.session.commit()
    flash("Andamento registrado.", "success")
    return redirect(url_for("crise.detalhe", crise_id=crise.id))


@crise_bp.route("/<int:crise_id>/encerrar", methods=["POST"])
@login_required
def encerrar(crise_id):
    crise = _carregar(crise_id)
    crise.status = "Fechada"
    crise.encerrado_em = agora()
    crise.solucao = (request.form.get("solucao") or crise.solucao or "").strip()
    crise.causa_raiz = (request.form.get("causa_raiz") or crise.causa_raiz or "").strip()
    _log(crise, "Crise encerrada.")
    db.session.commit()
    flash("Crise encerrada.", "success")
    return redirect(url_for("crise.detalhe", crise_id=crise.id))


@crise_bp.route("/<int:crise_id>/pdf")
@login_required
def pdf(crise_id):
    from flask import send_file

    crise = _carregar(crise_id)
    try:
        caminho = gerar_pdf_crise(crise)
    except Exception as exc:  # noqa: BLE001
        flash(f"Não foi possível gerar o PDF: {exc}", "danger")
        return redirect(url_for("crise.detalhe", crise_id=crise.id))
    return send_file(caminho, mimetype="application/pdf", download_name=caminho.name)


@crise_bp.route("/<int:crise_id>/excluir", methods=["POST"])
@login_required
@gestor_requerido
def excluir(crise_id):
    crise = _carregar(crise_id)
    identificador = crise.identificador
    db.session.delete(crise)
    db.session.commit()
    flash(f"{identificador} excluída.", "success")
    return redirect(url_for("crise.lista"))
