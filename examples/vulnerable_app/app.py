"""Намеренно уязвимое демо-приложение для проверки агентов.

НЕ запускать в проде. Используется только как цель анализа для системы.
"""
import hashlib
import os
import sqlite3
import subprocess

from flask import Flask, request, send_file

app = Flask(__name__)

# Захардкоженный секрет — уязвимость для secrets-специалиста.
app.secret_key = "super-secret-key-12345"
DB_API_TOKEN = "sk-live-9c8b7a6d5e4f3g2h1i"


def get_db():
    return sqlite3.connect("users.db")


@app.route("/login", methods=["POST"])
def login():
    # SQL injection: пользовательский ввод напрямую в запрос.
    username = request.form["username"]
    password = request.form["password"]
    query = "SELECT * FROM users WHERE name = '%s' AND pass = '%s'" % (username, password)
    cur = get_db().execute(query)
    return "ok" if cur.fetchone() else "fail"


@app.route("/user/<user_id>")
def get_user(user_id):
    # IDOR: нет проверки, что текущий пользователь имеет доступ к user_id.
    cur = get_db().execute("SELECT name, email FROM users WHERE id = " + user_id)
    return str(cur.fetchone())


@app.route("/ping")
def ping():
    # Command injection: ввод попадает в shell.
    host = request.args.get("host", "127.0.0.1")
    return subprocess.check_output("ping -c 1 " + host, shell=True)


@app.route("/download")
def download():
    # Path traversal: имя файла не валидируется.
    name = request.args.get("name")
    return send_file(os.path.join("/var/data", name))


def hash_password(password):
    # Слабая криптография: MD5 без соли.
    return hashlib.md5(password.encode()).hexdigest()


if __name__ == "__main__":
    # Небезопасный дефолт: debug=True в боевом запуске.
    app.run(host="0.0.0.0", debug=True)
