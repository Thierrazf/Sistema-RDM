import os
import secrets
from datetime import datetime, timezone

import click
from flask import Flask, render_template, session
from flask_login import current_user

from .config import get_config  # carrega o .env ao ser importado
from .extensions import csrf, db, limiter, login_manager, migrate


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(get_config(config_name))

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["PDF_DIR"], exist_ok=True)

    # Extensões
    db.init_app(app)
    migrate.init_app(app, db, render_as_batch=True)  # batch = ALTER TABLE no SQLite
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    from .models import Equipe, Perfil, StatusAtividade, StatusRDM, User

    @login_manager.user_loader
    def carregar_usuario(user_id):
        user = db.session.get(User, int(user_id))
        return user if (user and user.pode_entrar) else None

    # Blueprints
    from .blueprints.admin import admin_bp
    from .blueprints.auth import auth_bp
    from .blueprints.crise import crise_bp
    from .blueprints.painel import painel_bp
    from .blueprints.rdm import rdm_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(painel_bp)
    app.register_blueprint(rdm_bp, url_prefix="/rdm")
    app.register_blueprint(crise_bp, url_prefix="/crises")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # Sessão com expiração por inatividade
    @app.before_request
    def renovar_sessao():
        session.permanent = True
        app.permanent_session_lifetime = app.config["PERMANENT_SESSION_LIFETIME"]

    from .security import aplicar_cabecalhos_seguranca

    app.after_request(aplicar_cabecalhos_seguranca)

    # Contexto disponível em todos os templates
    @app.context_processor
    def injetar_contexto():
        return {
            "Equipe": Equipe,
            "Perfil": Perfil,
            "StatusRDM": StatusRDM,
            "StatusAtividade": StatusAtividade,
            "ano_atual": datetime.now(timezone.utc).year,
        }

    @app.template_filter("dt")
    def formatar_datahora(valor, formato="%d/%m/%Y %H:%M"):
        if not valor:
            return "—"
        return valor.strftime(formato)

    # Erros
    for codigo in (401, 403, 404, 429, 500):
        app.register_error_handler(codigo, _pagina_erro)

    _registrar_comandos(app)
    return app


def _pagina_erro(erro):
    codigo = getattr(erro, "code", 500)
    mensagens = {
        401: ("Sessão encerrada", "Faça login novamente para continuar."),
        403: ("Sem permissão", "Seu perfil não tem acesso a esta área."),
        404: ("Página não encontrada", "O endereço acessado não existe."),
        429: ("Muitas tentativas", "Aguarde alguns minutos antes de tentar de novo."),
        500: ("Erro no servidor", "A operação não foi concluída. Registre um chamado."),
    }
    titulo, texto = mensagens.get(codigo, mensagens[500])
    if codigo == 500:
        db.session.rollback()
    return render_template("errors/erro.html", codigo=codigo, titulo=titulo, texto=texto), codigo


def _registrar_comandos(app: Flask) -> None:
    from .models import CatalogoAtividade, Equipe, Perfil, User

    @app.cli.command("criar-admin")
    @click.option("--email", default=None)
    @click.option("--nome", default=None)
    def criar_admin(email, nome):
        """Cria o primeiro administrador. Substitui a antiga rota /seed-user."""
        email = (email or os.getenv("ADMIN_EMAIL") or "").strip().lower()
        nome = nome or os.getenv("ADMIN_NOME") or "Administrador"
        if not email:
            raise click.ClickException("Informe --email ou defina ADMIN_EMAIL no .env")

        if db.session.query(User).filter_by(email=email).first():
            raise click.ClickException(f"Já existe usuário com o e-mail {email}")

        senha = click.prompt("Senha", hide_input=True, confirmation_prompt=True)
        from .security import validar_senha

        erros = validar_senha(senha)
        if erros:
            raise click.ClickException("A senha precisa " + ", ".join(erros) + ".")

        u = User(nome=nome, email=email, perfil=Perfil.ADMIN, pode_enviar_email=True)
        u.definir_senha(senha)
        db.session.add(u)
        db.session.commit()
        click.echo(f"Administrador criado: {email}")

    @app.cli.command("testar-email")
    @click.option("--para", required=True, help="Endereço que receberá a mensagem de teste.")
    def testar_email(para):
        """Envia um e-mail de teste e mostra o erro exato em caso de falha."""
        cfg = app.config
        from .services.email_service import backend_ativo, enviar

        backend = backend_ativo(cfg)

        def oculto(valor):
            if not valor:
                return "(vazio)"
            return f"definido ({len(valor)} caracteres, termina em ...{valor[-4:]})"

        click.echo(f"Mecanismo de envio: {backend.upper()}")
        click.echo(f"  EMAIL_REMETENTE .: {cfg['EMAIL_REMETENTE'] or '(vazio)'}")

        if backend == "graph":
            click.echo(f"  GRAPH_TENANT_ID .: {cfg['GRAPH_TENANT_ID'] or '(vazio)'}")
            click.echo(f"  GRAPH_CLIENT_ID .: {cfg['GRAPH_CLIENT_ID'] or '(vazio)'}")
            click.echo(f"  GRAPH_SECRET ....: {oculto(cfg['GRAPH_CLIENT_SECRET'])}")
            obrigatorios = (
                "GRAPH_TENANT_ID", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
                "EMAIL_REMETENTE",
            )
        else:
            click.echo(f"  SMTP_HOST .......: {cfg['SMTP_HOST'] or '(vazio)'}")
            click.echo(f"  SMTP_PORT .......: {cfg['SMTP_PORT']}")
            click.echo(f"  SMTP_USER .......: {cfg['SMTP_USER'] or '(vazio)'}")
            click.echo(f"  SMTP_PASSWORD ...: {oculto(cfg['SMTP_PASSWORD'])}")
            obrigatorios = ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_REMETENTE")
        click.echo("")

        faltando = [nome for nome in obrigatorios if not cfg[nome]]
        if faltando:
            raise click.ClickException(
                "Faltam no .env: " + ", ".join(faltando) + ". "
                "Preencha e rode o comando de novo."
            )

        if backend == "smtp" and cfg["SMTP_USER"].lower() != cfg["EMAIL_REMETENTE"].lower():
            click.echo(
                "Aviso: SMTP_USER e EMAIL_REMETENTE são diferentes. A maioria dos "
                "provedores recusa enviar em nome de outro endereço sem permissão "
                "explícita de 'enviar como'.\n"
            )

        click.echo(f"Enviando para {para}...")
        ok, erro = enviar(
            [para],
            "Teste de envio — Gestão de Mudanças",
            "<p>Se você recebeu esta mensagem, o envio de e-mail está funcionando.</p>",
            "Se voce recebeu esta mensagem, o envio de e-mail esta funcionando.",
        )

        if ok:
            click.echo("Enviado. Confira a caixa de entrada e o spam.")
        else:
            click.echo(f"FALHOU: {erro}\n")
            texto = (erro or "").lower()
            if "smtpclientauthentication is disabled" in texto:
                click.echo(
                    "O tenant tem o SMTP desativado pela Microsoft — nenhuma senha\n"
                    "vai funcionar por esse caminho. Use a Graph API: preencha\n"
                    "GRAPH_TENANT_ID, GRAPH_CLIENT_ID e GRAPH_CLIENT_SECRET no .env.\n"
                    "O README traz o passo a passo do registro no Entra ID."
                )
            elif "authentication" in texto or "535" in texto:
                click.echo(
                    "Isso é recusa de autenticação. Causas comuns:\n"
                    "  - senha incorreta;\n"
                    "  - conta com MFA (use senha de aplicativo);\n"
                    "  - SMTP AUTH desabilitado na caixa pelo administrador."
                )
            elif "5.7.60" in texto or "send as" in texto:
                click.echo(
                    "A conta autenticada não tem permissão para enviar como o "
                    "endereço em EMAIL_REMETENTE. Use o mesmo endereço nos dois campos."
                )
            elif "timed out" in texto or "getaddrinfo" in texto or "not known" in texto:
                click.echo(
                    "Não houve conexão com o servidor. Verifique SMTP_HOST, a porta "
                    "e se o firewall da rede libera a saída na porta 587."
                )
            raise SystemExit(1)

    @app.cli.command("carregar-pessoas")
    def carregar_pessoas():
        """Cadastra as pessoas que aparecem nos seletores da RDM.

        Cria como 'somente referência': aparecem como solicitante, revisor ou
        autorizador, mas não acessam o sistema. Para dar acesso a alguma delas,
        edite em Administração > Usuários e defina uma senha.
        """
        # (nome, cargo, e-mail, perfil, equipe)
        # Cargo curto aparece antes do nome nos documentos ("Ten Cel Fulano").
        # Para os analistas o cargo fica vazio: a equipe já identifica a área,
        # e o título completo prefixando o nome ficaria ilegível no e-mail.
        pessoas = [
            ("Carlos Mendes", "2º Ten", "carlos.mendes@exemplo.com.br",
             Perfil.GESTOR, None),
            ("Roberto Alves", "Ten Cel", "roberto.alves@exemplo.com.br",
             Perfil.GESTOR, None),
            ("Paulo Ribeiro", "", "paulo.ribeiro@exemplo.com.br",
             Perfil.ANALISTA, Equipe.INFRAESTRUTURA),
            ("Marcos Teixeira", "", "marcos.teixeira@exemplo.com.br",
             Perfil.ANALISTA, Equipe.INFRAESTRUTURA),
            ("Bruno Lima", "", "bruno.lima@exemplo.com.br",
             Perfil.ANALISTA, Equipe.BACKEND),
            ("Ana Souza", "", "ana.souza@exemplo.com.br",
             Perfil.ANALISTA, Equipe.FRONTEND),
            ("João Pereira", "", "joao.pereira@exemplo.com.br",
             Perfil.ANALISTA, Equipe.BANCO_DADOS),
        ]
        criados = 0
        for nome, cargo, email, perfil, equipe in pessoas:
            if db.session.query(User).filter_by(email=email).first():
                click.echo(f"já existe: {email}")
                continue
            u = User(
                nome=nome,
                cargo=cargo or None,
                email=email,
                perfil=perfil,
                equipe=equipe,
                ativo=True,
                somente_referencia=True,
            )
            # Sem acesso: senha aleatória que ninguém conhece nem usa.
            u.definir_senha(secrets.token_urlsafe(32))
            db.session.add(u)
            criados += 1
        db.session.commit()
        click.echo(
            f"{criados} pessoa(s) cadastrada(s). Ajuste os e-mails em "
            "Administração > Usuários se forem diferentes."
        )

    @app.cli.command("carregar-catalogo")
    def carregar_catalogo():
        """Popula o catálogo de atividades recorrentes por equipe."""
        base = {
            Equipe.INFRAESTRUTURA: [
                ("Abrir janela de manutenção no monitoramento (Zabbix)", 5),
                ("Snapshot das máquinas virtuais envolvidas", 20),
                ("Reinicialização de serviço/aplicação em produção", 15),
                ("Aplicação de patch de sistema operacional", 45),
                ("Ajuste de regra de firewall / liberação de porta", 20),
                ("Renovação de certificado digital", 30),
            ],
            Equipe.FRONTEND: [
                ("Publicação de build no servidor web", 20),
                ("Limpeza de cache/CDN após publicação", 10),
                ("Validação de responsividade e navegadores homologados", 30),
                ("Rollback de versão do pacote publicado", 15),
            ],
            Equipe.BACKEND: [
                ("Deploy de nova versão da API", 25),
                ("Atualização de variáveis de ambiente do serviço", 10),
                ("Execução de rotina de migração de dados", 40),
                ("Validação de endpoints críticos pós-deploy", 20),
                ("Rollback para a release anterior", 20),
            ],
            Equipe.BANCO_DADOS: [
                ("Backup full antes da alteração", 40),
                ("Execução de script DDL (criação/alteração de objetos)", 20),
                ("Execução de script DML (carga/correção de dados)", 30),
                ("Reindexação / atualização de estatísticas", 45),
                ("Validação de integridade referencial pós-execução", 20),
                ("Restore do backup em caso de falha", 60),
            ],
        }
        criados = 0
        for equipe, itens in base.items():
            for descricao, duracao in itens:
                existe = (
                    db.session.query(CatalogoAtividade)
                    .filter_by(equipe=equipe, descricao=descricao)
                    .first()
                )
                if existe:
                    continue
                db.session.add(
                    CatalogoAtividade(
                        equipe=equipe, descricao=descricao, duracao_min=duracao
                    )
                )
                criados += 1
        db.session.commit()
        click.echo(f"{criados} atividades adicionadas ao catálogo.")
