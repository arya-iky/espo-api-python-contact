EspoCRM Relational Data Dashboard

Flask + EspoCRM REST API + Accurate Online

Prototype aplikasi CRM untuk mengelola data relasional dalam jumlah besar, menyediakan dashboard & analytics, serta mengintegrasikan Opportunity Closed Won → Accurate Online Sales Invoice.

 Highlights

 CRM Dashboard — Account, Contact, Opportunity, Task, Case, dan PIC/User

 Search / Sort / Filter — server-side

 Server-side Pagination — browser tidak memuat seluruh 10.000+ record

 Relationship Explorer — melihat relasi antar entity

 Contact Data Quality — memantau kelengkapan data

 Analytics — pipeline, workload PIC, Task, overdue Task, dan Case
 
 Large Dataset Generator — pengujian skala besar
 
 Accurate Integration — Closed Won → Sales Invoice
 
 Idempotency — mencegah transaksi duplikat
 
 Create / Update Sync — update transaksi yang sudah tersinkron
 
 Sync State & Error Tracking
 
 Architecture

┌───────────────────────┐
│       Browser         │
│   HTML / CSS / JS     │
└───────────┬───────────┘
            │
            ▼
┌───────────────────────┐
│      Flask App        │
│      web_app.py       │
└───────┬─────────┬─────┘
        │         │
        ▼         ▼
┌────────────┐  ┌────────────────┐
│ EspoCRM    │  │ Accurate Online│
│ REST API   │  │ OAuth / API    │
└────────────┘  └────────────────┘
        │
        ▼
┌───────────────────────┐
│ SQLite Local Store    │
│ sync / job / state    │
└───────────────────────┘

Relasi data

Account
├── Contact
│   └── Opportunity
│       └── Task ── User / PIC
└── Opportunity
    └── Task

 Tech Stack

Backend

Python

Flask

Requests

python-dotenv

SQLite

Frontend

HTML

CSS

JavaScript

External Services

EspoCRM REST API

Accurate Online API / OAuth

 Project Structure

espo-api-python/
│
├── api.py
├── web_app.py
├── accurate_integration.py
├── accurate_oauth.py
├── app_store.py
├── config.py
├── requirements.txt
├── .env.example
├── .gitignore
│
├── templates/
│   └── index.html
│
├── static/
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   └── app.js
│   └── assets/
│       └── backgrounds/
│
└── runtime/
    └── app.sqlite3

runtime/ digunakan untuk storage lokal aplikasi dan tidak perlu di-upload ke Git.

🚀 Quick Start

1. Jalankan EspoCRM

cd "D:\espocrm_docker"
docker compose up -d

Pastikan:

http://localhost:8081

2. Buat virtual environment

python -m venv .venv
.\.venv\Scripts\Activate.ps1

3. Install dependency

python -m pip install --upgrade pip
pip install -r requirements.txt

4. Siapkan konfigurasi

Copy-Item .env.example testumbrella.env

Contoh konfigurasi Accurate:

ACCURATE_CLIENT_ID=
ACCURATE_CLIENT_SECRET=
ACCURATE_REDIRECT_URI=http://localhost:5000/callback
ACCURATE_DATABASE_ALIAS=
ACCURATE_SCOPE=
ACCURATE_CUSTOMER_NO=
ACCURATE_SYNC_WORKER=false

Jangan commit secret, token, password, atau session ID.

5. Jalankan Flask

python web_app.py

Buka:

http://localhost:5000

🔌 Endpoint Penting

Endpoint

Fungsi

/

Dashboard utama

/api/health

Cek koneksi EspoCRM

/api/stats

Statistik entity

/api/accurate/status

Status koneksi Accurate

/accurate/connect

Memulai OAuth Accurate

/callback

OAuth callback

 Dashboard & Analytics

Mencakup:

Distribusi stage Opportunity

Nilai Opportunity per stage

Opportunity berdasarkan periode

Workload PIC

Status Task

Overdue Task

Case

Contact data quality

Relationship health

Analytics diproses di backend dan menggunakan cache agar browser tetap ringan.

 Server-side Data Handling

Table menggunakan pagination server-side:

page
page_size
search
sort
order

Opportunity juga mendukung filter:

Search
Stage
PIC / User
Priority
Account
Contact
Sort / Order

Browser hanya menerima halaman yang sedang dibuka, sehingga dataset 10.000+ record tetap lebih ringan.

 Large Dataset Testing

Generator tersedia di api.py:

generate_large_accounts()
generate_large_contacts()
generate_large_opportunities()
generate_large_tasks()
generate_large_crm_dataset()

Alur:

Account
   ↓
Contact
   ↓
Opportunity
   ↓
Task

Uji kecil dulu

python -c "import api; print(api.generate_large_crm_dataset(account_count=100, contact_count=100, opportunity_count=100, task_count=100))"

Setelah alur valid, jumlah record dapat dinaikkan sesuai kebutuhan.

 Accurate Online Integration

Alurnya:

Opportunity EspoCRM
        │
        ▼
   Stage = Closed Won?
        │
        ▼
   Validasi + Mapping
        │
        ├── Customer
        ├── Item
        ├── Amount
        └── Close Date
        │
        ▼
Accurate Sales Invoice
        │
        ▼
External ID + Sync State

Sync behavior

Create

Belum pernah sync
      ↓
CREATE Invoice

Skipped

Sudah pernah sync
+ data tidak berubah
      ↓
SKIPPED

Update

Sudah pernah sync
+ data berubah
      ↓
UPDATE Invoice

Failure

Validation / request gagal
      ↓
FAILED

Opportunity yang masih Proposal, Negotiation, dan stage non-Closed Won tidak dikirim sebagai invoice.

Background worker

Default:

ACCURATE_SYNC_WORKER=false

Worker historis tersedia, tetapi sebaiknya tidak diaktifkan sembarangan pada dataset besar.

OAuth Accurate

Mulai OAuth:

http://localhost:5000/accurate/connect

Callback:

http://localhost:5000/callback

Cek status:

http://localhost:5000/api/accurate/status

Redirect URI harus sama dengan konfigurasi Accurate Developer.

 Security

Jangan commit:

testumbrella.env
accurate_token.json
accurate_connection.json
accurate_sync.json
accurate_oauth_debug.txt

Jangan masukkan ke repository publik:

Client Secret

Access Token

Session ID

Password EspoCRM

API Key

Troubleshooting

EspoCRM tidak terhubung

docker ps
cd "D:\espocrm_docker"
docker compose up -d

Flask tidak start

.\.venv\Scripts\Activate.ps1
python web_app.py

Port 5000 sudah digunakan

Hentikan instance lama dengan:

CTRL + C

Accurate belum terhubung

Periksa:

testumbrella.env

Client ID / Client Secret

Redirect URI

Database alias

Scope

Customer / Item mapping

 Project Status

Prototype — Active Development

Project ini dibuat untuk menunjukkan:

CRM Data
   +
Relationship
   +
Large Dataset
   +
Analytics
   +
Accurate Integration

Fokus utamanya mencakup server-side pagination, filtering, relationship data, analytics, large dataset testing, idempotency, update synchronization, dan error handling.

Terminal 1

cd "D:\espocrm_docker"
docker compose up -d

Terminal 2

cd "D:\Folder Tugas Phython Contat - BLTI\espo-api-python"
.\.venv\Scripts\Activate.ps1
python web_app.py

Buka:

http://localhost:5000
