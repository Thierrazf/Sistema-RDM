"""Confere os controles de segurança do sistema.

Roda com: python teste_seguranca.py
"""

from app import create_app
from app.config import ProductionConfig
from app.extensions import db
from app.models import Perfil, User

falhas = []


def checar(descricao, condicao):
    print(f"  {'ok  ' if condicao else 'FALHA'}  {descricao}")
    if not condicao:
        falhas.append(descricao)


app = create_app("testing")

with app.app_context():
    db.create_all()
    u = User(nome="Fernanda Lopes", email="fernanda@exemplo.com.br", perfil=Perfil.ADMIN)
    u.definir_senha("Janela@2026!ok")
    db.session.add(u)
    db.session.commit()

print("\nSenhas")
with app.app_context():
    u = db.session.query(User).first()
    checar("senha guardada como hash scrypt", u.senha_hash.startswith("scrypt:"))
    checar("senha em claro não aparece no hash", "Janela@2026!ok" not in u.senha_hash)
    checar("conferência aceita a senha correta", u.conferir_senha("Janela@2026!ok"))
    checar("conferência recusa senha errada", not u.conferir_senha("Janela@2026!oK"))

    from app.security import validar_senha

    checar("recusa senha curta", bool(validar_senha("Ab1!")))
    checar("recusa senha sem especial", bool(validar_senha("Abcdefghij1")))
    checar("aceita senha forte", not validar_senha("Janela@2026!ok"))

print("\nToken de reset")
with app.app_context():
    u = db.session.query(User).first()
    token = u.gerar_token_reset()
    db.session.commit()
    checar("token não é guardado em texto puro", u.reset_token_hash != token)
    checar("token válido é aceito", u.token_reset_valido(token))
    checar("token adulterado é recusado", not u.token_reset_valido(token[:-2] + "xx"))

print("\nCabeçalhos HTTP")
cliente = app.test_client()
r = cliente.get("/login")
checar("X-Frame-Options: DENY", r.headers.get("X-Frame-Options") == "DENY")
checar("X-Content-Type-Options: nosniff", r.headers.get("X-Content-Type-Options") == "nosniff")
checar("Content-Security-Policy presente", "default-src 'self'" in (r.headers.get("Content-Security-Policy") or ""))
checar("Referrer-Policy presente", bool(r.headers.get("Referrer-Policy")))

print("\nControle de acesso")
for rota in ["/", "/rdm/", "/crises/", "/admin/usuarios", "/admin/auditoria"]:
    r = cliente.get(rota)
    checar(f"{rota} exige autenticação", r.status_code in (302, 401))

r = cliente.post("/login", data={"email": "fernanda@exemplo.com.br", "senha": "Janela@2026!ok"})
r = cliente.get("/rdm/nova")
checar("formulário traz token CSRF", b"csrf_token" in r.data)

print("\nRedirecionamento")
r = cliente.get("/login")
cliente.get("/logout")
r = cliente.post(
    "/login?next=https://site-externo.example/roubo",
    data={"email": "fernanda@exemplo.com.br", "senha": "Janela@2026!ok"},
)
checar("ignora redirecionamento para domínio externo", "site-externo" not in (r.headers.get("Location") or ""))

print("\nConfiguração de produção")
import os

os.environ["SECRET_KEY"] = ""
try:
    ProductionConfig()
    checar("recusa subir sem SECRET_KEY", False)
except RuntimeError:
    checar("recusa subir sem SECRET_KEY", True)

os.environ["SECRET_KEY"] = "curta"
try:
    ProductionConfig()
    recusou = False
except RuntimeError:
    recusou = True
checar("recusa SECRET_KEY fraca", recusou)

checar("rota /seed-user não existe", "/seed-user" not in [str(r) for r in app.url_map.iter_rules()])

print()
if falhas:
    print(f"{len(falhas)} verificação(ões) falharam:")
    for f in falhas:
        print("  -", f)
    raise SystemExit(1)
print("Todas as verificações de segurança passaram.")
