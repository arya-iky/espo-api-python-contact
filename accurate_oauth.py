"""
Accurate Online OAuth Test
============================================================

Tujuan:
- Membaca credential dari testumbrella.env
- Membuka OAuth Accurate Online melalui Google Chrome
- Menerima authorization code pada callback
- Menukar authorization code menjadi access token
- Mengambil daftar database Accurate
- Mencari database "Umbrella"
- Membuka database dan memperoleh host + session
- Menguji akses API Item menggunakan X-Session-ID

Project:
EspoCRM -> Accurate Online Integration
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv
from flask import Flask, request


# ============================================================
# PATH
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

ENV_FILE = BASE_DIR / "testumbrella.env"
TOKEN_FILE = BASE_DIR / "accurate_token.json"
CONNECTION_FILE = BASE_DIR / "accurate_connection.json"


# ============================================================
# LOAD ENV
# ============================================================

if not ENV_FILE.exists():
    raise FileNotFoundError(
        "File environment tidak ditemukan:\n"
        f"{ENV_FILE}\n\n"
        "Pastikan file berikut ada di folder yang sama dengan "
        "accurate_oauth.py:\n"
        "testumbrella.env"
    )

# override=True supaya nilai dari testumbrella.env menjadi sumber utama.
load_dotenv(dotenv_path=ENV_FILE, override=True)


# ============================================================
# CONFIG
# ============================================================

CLIENT_ID = os.getenv("ACCURATE_CLIENT_ID", "").strip()
CLIENT_SECRET = os.getenv("ACCURATE_CLIENT_SECRET", "").strip()

REDIRECT_URI = os.getenv(
    "ACCURATE_REDIRECT_URI",
    "http://localhost:5000/callback",
).strip()

DATABASE_ALIAS = os.getenv(
    "ACCURATE_DATABASE_ALIAS",
    "Umbrella",
).strip()

# Untuk test awal, item_view cukup untuk menguji OAuth + baca Item.
# Scope transaksi akan ditambahkan setelah endpoint transaksi final
# sudah ditentukan.
SCOPE = os.getenv(
    "ACCURATE_SCOPE",
    "item_view",
).strip()


# ============================================================
# ACCURATE ENDPOINT
# ============================================================

AUTHORIZE_URL = "https://account.accurate.id/oauth/authorize"
TOKEN_URL = "https://account.accurate.id/oauth/token"
DB_LIST_URL = "https://account.accurate.id/api/db-list.do"
OPEN_DB_URL = "https://account.accurate.id/api/open-db.do"


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)

# State diganti setiap kali user membuka halaman login.
CURRENT_STATE = None


# ============================================================
# HELPER
# ============================================================

def save_json(file_path: Path, data: dict) -> None:
    """Menyimpan dictionary ke JSON lokal."""
    with file_path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            indent=4,
            ensure_ascii=False,
        )


def mask_value(value: str, visible: int = 8) -> str:
    """Mask value untuk log agar credential tidak dicetak penuh."""
    if not value:
        return "(kosong)"

    if len(value) <= visible:
        return "*" * len(value)

    return value[:visible] + "..."


def validate_config() -> None:
    """Memastikan credential dan callback tersedia."""
    missing = []

    if not CLIENT_ID:
        missing.append("ACCURATE_CLIENT_ID")

    if not CLIENT_SECRET:
        missing.append("ACCURATE_CLIENT_SECRET")

    if not REDIRECT_URI:
        missing.append("ACCURATE_REDIRECT_URI")

    if missing:
        raise RuntimeError(
            "Konfigurasi Accurate belum lengkap.\n\n"
            f"Variabel yang belum tersedia: {', '.join(missing)}\n\n"
            f"File yang dibaca:\n{ENV_FILE}"
        )


def build_authorize_url() -> str:
    """
    Membuat authorization URL Accurate.

    Scope dikirim dengan spasi antar-scope, sesuai dokumentasi Accurate.
    """
    global CURRENT_STATE

    CURRENT_STATE = secrets.token_urlsafe(32)

    params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
        "state": CURRENT_STATE,
    }

    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def get_basic_auth_header() -> str:
    """
    Membuat:
    Authorization: Basic base64(ClientID:ClientSecret)
    """
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode("utf-8")

    encoded = base64.b64encode(raw).decode("ascii")

    return f"Basic {encoded}"


def exchange_code_for_token(code: str) -> dict:
    """Menukar authorization code menjadi access token."""
    headers = {
        "Authorization": get_basic_auth_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }

    data = {
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }

    response = requests.post(
        TOKEN_URL,
        headers=headers,
        data=data,
        timeout=30,
    )

    response.raise_for_status()

    token_data = response.json()

    if "access_token" not in token_data:
        raise RuntimeError(
            "Response token tidak memiliki access_token.\n"
            f"{json.dumps(token_data, indent=4, ensure_ascii=False)}"
        )

    return token_data


def get_database_list(access_token: str) -> list[dict]:
    """Mengambil daftar database yang dapat diakses oleh access token."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    response = requests.get(
        DB_LIST_URL,
        headers=headers,
        timeout=30,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("s"):
        raise RuntimeError(
            "API db-list.do gagal.\n"
            f"{json.dumps(result, indent=4, ensure_ascii=False)}"
        )

    databases = result.get("d", [])

    if not isinstance(databases, list):
        raise RuntimeError(
            "Format daftar database dari Accurate tidak sesuai."
        )

    return databases


def find_database(
    databases: list[dict],
    target_alias: str,
) -> dict | None:
    """Mencari database berdasarkan alias, case-insensitive."""
    target = target_alias.strip().casefold()

    for database in databases:
        alias = str(
            database.get("alias", "")
        ).strip().casefold()

        if alias == target:
            return database

    return None


def open_database(
    access_token: str,
    database_id: int | str,
) -> dict:
    """Membuka database untuk mendapatkan host dan session."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }

    response = requests.get(
        OPEN_DB_URL,
        headers=headers,
        params={"id": database_id},
        timeout=30,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("s"):
        raise RuntimeError(
            "Open Database gagal.\n"
            f"{json.dumps(result, indent=4, ensure_ascii=False)}"
        )

    host = result.get("host")
    session = result.get("session")

    if not host or not session:
        raise RuntimeError(
            "Open Database berhasil, tetapi host/session tidak ditemukan."
        )

    return result


def test_item_api(
    access_token: str,
    host: str,
    session: str,
) -> dict:
    """
    Test API Accurate pertama menggunakan scope item_view.

    Endpoint:
    /accurate/api/item/list.do

    Header:
    Authorization: Bearer <token>
    X-Session-ID: <session>
    """
    host = host.rstrip("/")

    url = f"{host}/accurate/api/item/list.do"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "X-Session-ID": session,
        "Accept": "application/json",
    }

    params = {
        "fields": "id,name,no",
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )

    response.raise_for_status()

    result = response.json()

    if not result.get("s"):
        raise RuntimeError(
            "API Item gagal.\n"
            f"{json.dumps(result, indent=4, ensure_ascii=False)}"
        )

    return result


def find_chrome() -> str | None:
    """
    Mencari executable Google Chrome pada Windows.

    Tidak membuat profile Chrome baru, sehingga session login yang
    sudah ada pada Chrome dapat digunakan.
    """
    candidates = [
        os.environ.get("PROGRAMFILES"),
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("LOCALAPPDATA"),
    ]

    possible_paths = []

    for base in candidates:
        if not base:
            continue

        possible_paths.extend(
            [
                Path(base)
                / "Google"
                / "Chrome"
                / "Application"
                / "chrome.exe",
                Path(base)
                / "Google"
                / "Chrome"
                / "Application"
                / "chrome_proxy.exe",
            ]
        )

    for path in possible_paths:
        if path.is_file():
            return str(path)

    return None


def open_in_chrome(url: str) -> bool:
    """
    Membuka URL menggunakan Google Chrome.

    Return:
    True  -> Chrome berhasil dipanggil
    False -> Chrome tidak ditemukan
    """
    chrome_path = find_chrome()

    if not chrome_path:
        return False

    try:
        subprocess.Popen(
            [
                chrome_path,
                "--new-window",
                url,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True

    except OSError as exc:
        print(f"[WARNING] Gagal membuka Chrome: {exc}")
        return False


# ============================================================
# ROUTE HOME
# ============================================================

@app.route("/")
def index():
    """Halaman awal untuk memulai OAuth."""

    auth_url = build_authorize_url()

    # Simpan URL ke file debug lokal supaya mudah diperiksa bila perlu.
    debug_file = BASE_DIR / "accurate_oauth_debug.txt"
    debug_file.write_text(
        (
            "Authorization URL:\n"
            f"{auth_url}\n\n"
            "Catatan:\n"
            "- Jangan membagikan URL ini jika berisi state.\n"
            "- Client Secret tidak dicetak ke file ini.\n"
        ),
        encoding="utf-8",
    )

    return f"""
    <!DOCTYPE html>
    <html lang="id">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>EspoCRM - Accurate Integration</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f4f6f9;
                padding: 40px;
                margin: 0;
            }}

            .container {{
                max-width: 760px;
                margin: 30px auto;
                background: #ffffff;
                padding: 32px;
                border-radius: 14px;
                box-shadow: 0 4px 18px rgba(0, 0, 0, 0.08);
            }}

            h1 {{
                margin-top: 0;
            }}

            .info {{
                background: #f1f5f9;
                padding: 18px;
                border-radius: 10px;
                line-height: 1.7;
                margin: 22px 0;
            }}

            .button {{
                display: inline-block;
                padding: 13px 20px;
                background: #2563eb;
                color: #ffffff;
                text-decoration: none;
                border-radius: 9px;
                font-weight: bold;
            }}

            .button:hover {{
                opacity: 0.92;
            }}

            code {{
                background: #e5e7eb;
                padding: 3px 6px;
                border-radius: 5px;
            }}

            .note {{
                margin-top: 20px;
                color: #475569;
                font-size: 14px;
            }}
        </style>
    </head>

    <body>
        <div class="container">
            <h1>EspoCRM → Accurate Integration</h1>

            <p>
                OAuth Test Server berhasil dijalankan.
            </p>

            <div class="info">
                <b>Database target:</b> {DATABASE_ALIAS}<br>
                <b>Scope:</b> {SCOPE}<br>
                <b>Callback:</b> <code>{REDIRECT_URI}</code>
            </div>

            <a class="button" href="{auth_url}">
                Hubungkan ke Accurate
            </a>

            <p class="note">
                Klik tombol di atas untuk memulai Authorization Code OAuth.
            </p>
        </div>
    </body>
    </html>
    """


# ============================================================
# ROUTE CALLBACK
# ============================================================

@app.route("/callback")
def callback():
    """Menerima callback OAuth dari Accurate."""

    global CURRENT_STATE

    # --------------------------------------------------------
    # 1. HANDLE ERROR DARI ACCURATE
    # --------------------------------------------------------

    error = request.args.get("error")

    if error:
        description = request.args.get(
            "error_description",
            "Tidak ada keterangan tambahan.",
        )

        return f"""
        <h1>❌ OAuth Gagal</h1>
        <p><b>Error:</b> {error}</p>
        <p><b>Keterangan:</b> {description}</p>
        <p>
            Periksa Client ID, redirect URI, dan scope
            pada konfigurasi Accurate.
        </p>
        """, 400

    # --------------------------------------------------------
    # 2. AMBIL STATE + AUTHORIZATION CODE
    # --------------------------------------------------------

    returned_state = request.args.get("state")
    code = request.args.get("code")

    if not CURRENT_STATE:
        return """
        <h1>❌ OAuth Gagal</h1>
        <p>State OAuth tidak tersedia. Mulai ulang dari halaman utama.</p>
        """, 400

    if returned_state != CURRENT_STATE:
        return """
        <h1>❌ OAuth Gagal</h1>
        <p>State OAuth tidak cocok.</p>
        <p>Silakan kembali ke halaman utama dan ulangi proses.</p>
        """, 400

    if not code:
        return """
        <h1>❌ OAuth Gagal</h1>
        <p>Authorization code tidak ditemukan.</p>
        """, 400

    # --------------------------------------------------------
    # 3. EXCHANGE CODE -> ACCESS TOKEN
    # --------------------------------------------------------

    try:
        token_data = exchange_code_for_token(code)

    except requests.HTTPError as exc:
        status_code = (
            exc.response.status_code
            if exc.response is not None
            else 500
        )

        response_text = (
            exc.response.text
            if exc.response is not None
            else str(exc)
        )

        return f"""
        <h1>❌ Gagal Mendapatkan Access Token</h1>

        <p><b>HTTP Status:</b> {status_code}</p>

        <pre>{response_text}</pre>
        """, 500

    except requests.RequestException as exc:
        return f"""
        <h1>❌ Gagal Mendapatkan Access Token</h1>
        <pre>{exc}</pre>
        """, 500

    except Exception as exc:
        return f"""
        <h1>❌ Gagal Mendapatkan Access Token</h1>
        <pre>{exc}</pre>
        """, 500

    save_json(TOKEN_FILE, token_data)

    access_token = token_data["access_token"]

    # --------------------------------------------------------
    # 4. GET DATABASE LIST
    # --------------------------------------------------------

    try:
        databases = get_database_list(access_token)

    except Exception as exc:
        return f"""
        <h1>⚠️ OAuth Berhasil, Database Gagal Diambil</h1>
        <p>Access Token berhasil diperoleh.</p>
        <pre>{exc}</pre>
        """, 500

    # --------------------------------------------------------
    # 5. FIND DATABASE UMBRELLA
    # --------------------------------------------------------

    database = find_database(
        databases,
        DATABASE_ALIAS,
    )

    if database is None:
        aliases = [
            database.get("alias")
            for database in databases
        ]

        return f"""
        <h1>⚠️ OAuth Berhasil</h1>

        <p>
            Access Token berhasil diperoleh,
            tetapi database <b>{DATABASE_ALIAS}</b>
            tidak ditemukan.
        </p>

        <h3>Database yang tersedia:</h3>
        <pre>{json.dumps(aliases, indent=4, ensure_ascii=False)}</pre>
        """, 404

    database_id = database.get("id")
    database_alias = database.get("alias")

    if not database_id:
        return """
        <h1>❌ Database Tidak Valid</h1>
        <p>ID database tidak ditemukan.</p>
        """, 500

    # --------------------------------------------------------
    # 6. OPEN DATABASE
    # --------------------------------------------------------

    try:
        open_data = open_database(
            access_token,
            database_id,
        )

    except Exception as exc:
        return f"""
        <h1>❌ Gagal Membuka Database</h1>
        <p><b>Database:</b> {database_alias}</p>
        <pre>{exc}</pre>
        """, 500

    host = open_data.get("host")
    session = open_data.get("session")

    # --------------------------------------------------------
    # 7. TEST API ITEM
    # --------------------------------------------------------

    try:
        item_result = test_item_api(
            access_token,
            host,
            session,
        )

    except requests.HTTPError as exc:
        status_code = (
            exc.response.status_code
            if exc.response is not None
            else 500
        )

        response_text = (
            exc.response.text
            if exc.response is not None
            else str(exc)
        )

        return f"""
        <h1>⚠️ OAuth + Open Database Berhasil</h1>

        <p>
            Database <b>{database_alias}</b> berhasil dibuka,
            tetapi test API Item gagal.
        </p>

        <p><b>HTTP Status:</b> {status_code}</p>

        <pre>{response_text}</pre>

        <p>
            Kemungkinan berikutnya adalah scope API belum mencukupi
            atau endpoint/parameter perlu disesuaikan.
        </p>
        """, 500

    except Exception as exc:
        return f"""
        <h1>⚠️ OAuth + Open Database Berhasil</h1>
        <p>Test API Item gagal.</p>
        <pre>{exc}</pre>
        """, 500

    # --------------------------------------------------------
    # 8. SIMPAN CONNECTION INFO
    # --------------------------------------------------------

    connection_data = {
        "database_id": database_id,
        "database_alias": database_alias,
        "host": host,
        "session": session,
    }

    save_json(
        CONNECTION_FILE,
        connection_data,
    )

    # --------------------------------------------------------
    # 9. SIAPKAN RINGKASAN ITEM
    # --------------------------------------------------------

    items = item_result.get("d", [])

    if not isinstance(items, list):
        items = []

    preview_items = items[:10]

    preview_html = ""

    if preview_items:
        rows = []

        for item in preview_items:
            item_id = item.get("id", "")
            item_no = item.get("no", "")
            item_name = item.get("name", "")

            rows.append(
                f"""
                <tr>
                    <td>{item_id}</td>
                    <td>{item_no}</td>
                    <td>{item_name}</td>
                </tr>
                """
            )

        preview_html = f"""
        <h3>Preview Item dari Accurate</h3>

        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>No</th>
                    <th>Nama</th>
                </tr>
            </thead>

            <tbody>
                {"".join(rows)}
            </tbody>
        </table>
        """
    else:
        preview_html = """
        <p>
            API berhasil tetapi belum ada item pada response pertama.
        </p>
        """

    # --------------------------------------------------------
    # 10. SUCCESS
    # --------------------------------------------------------

    # Session tidak ditampilkan agar tidak bocor ke browser.
    return f"""
    <!DOCTYPE html>
    <html lang="id">

    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">

        <title>Accurate Integration Berhasil</title>

        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #f4f6f9;
                padding: 40px;
                margin: 0;
            }}

            .container {{
                max-width: 900px;
                margin: 20px auto;
                background: white;
                padding: 30px;
                border-radius: 14px;
                box-shadow: 0 4px 18px rgba(0,0,0,0.08);
            }}

            .success {{
                color: #15803d;
            }}

            .box {{
                background: #f1f5f9;
                padding: 16px;
                border-radius: 10px;
                margin: 20px 0;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 15px;
            }}

            th, td {{
                border: 1px solid #d1d5db;
                padding: 10px;
                text-align: left;
            }}

            th {{
                background: #f8fafc;
            }}

            code {{
                background: #e5e7eb;
                padding: 3px 6px;
                border-radius: 5px;
            }}
        </style>
    </head>

    <body>
        <div class="container">

            <h1 class="success">
                ✅ Integrasi Accurate Berhasil
            </h1>

            <p>
                OAuth, Open Database, dan test API Item
                berhasil dijalankan.
            </p>

            <div class="box">
                <b>Database:</b> {database_alias}<br>
                <b>Database ID:</b> {database_id}<br>
                <b>Host:</b> {host}<br>
                <b>Scope:</b> {SCOPE}
            </div>

            <p>
                <b>Access Token:</b>
                berhasil diperoleh
            </p>

            <p>
                <b>X-Session-ID:</b>
                berhasil diperoleh dan digunakan
                untuk test API.
            </p>

            <p>
                <b>Jumlah item pada response pertama:</b>
                {len(items)}
            </p>

            {preview_html}

            <hr>

            <p>
                Token tersimpan lokal sebagai:
                <code>accurate_token.json</code>
            </p>

            <p>
                Informasi host/session tersimpan lokal sebagai:
                <code>accurate_connection.json</code>
            </p>

        </div>
    </body>
    </html>
    """


# ============================================================
# START SERVER
# ============================================================

def auto_open_browser() -> None:
    """
    Membuka localhost menggunakan Google Chrome.

    Chrome dipanggil tanpa profile baru agar session/login Chrome
    yang sudah ada dapat digunakan.
    """
    time.sleep(1)

    url = "http://localhost:5000"

    if open_in_chrome(url):
        print("[OK] Google Chrome dibuka.")
        print("[INFO] Session login Chrome yang aktif akan digunakan.")
        return

    print("[WARNING] Google Chrome tidak ditemukan otomatis.")
    print(f"[INFO] Buka manual: {url}")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    validate_config()

    print()
    print("=" * 65)
    print(" Accurate Online OAuth Test Server")
    print("=" * 65)
    print()
    print(f"ENV File       : {ENV_FILE}")
    print(f"Client ID      : {mask_value(CLIENT_ID)}")
    print(f"Database       : {DATABASE_ALIAS}")
    print(f"Scope          : {SCOPE}")
    print(f"Callback       : {REDIRECT_URI}")
    print()
    print("Server         : http://localhost:5000")
    print()
    print("Browser        : Google Chrome")
    print("Tekan CTRL+C untuk menghentikan server.")
    print("=" * 65)
    print()

    threading.Thread(
        target=auto_open_browser,
        daemon=True,
    ).start()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
    )
