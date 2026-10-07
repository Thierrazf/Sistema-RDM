"""Ponto de entrada da aplicação.

Desenvolvimento:  flask --app wsgi run --debug
Produção:         gunicorn -w 4 -b 0.0.0.0:8000 wsgi:app
"""

from app import create_app

app = create_app("production")

if __name__ == "__main__":
    # Nunca use debug=True em produção — use gunicorn atrás de um proxy HTTPS.
    app.run(host="127.0.0.1", port=5000, debug=False)
