EspoCRM Relational Data Dashboard & Accurate Online Integration

Aplikasi web berbasis Python yang mengambil data dari EspoCRM melalui REST API, menampilkan data CRM dalam dashboard web, menyediakan pengelolaan dan analitik data berukuran besar, serta mengintegrasikan Opportunity tertentu ke Accurate Online.

Catatan: versi project ini sudah berbeda dari versi awal yang hanya berfokus pada Contact Manager/Tkinter. Versi sekarang menggunakan Flask + HTML/CSS/JavaScript dan berfokus pada data relasional, dashboard, dataset besar, serta integrasi Accurate.

1. Gambaran Project

Project ini dibuat untuk menangani kondisi CRM dengan jumlah data besar, ketika data Account, Contact, Opportunity, Task, PIC/User, dan Case sudah banyak sehingga pencarian, pembacaan, dan pemantauan menjadi lebih sulit.

Aplikasi menyediakan lapisan Python yang berkomunikasi dengan EspoCRM dan web interface untuk:

menampilkan ringkasan data CRM;

menampilkan tabel data dengan pagination di server;

melakukan search, sort, dan filter pada data besar;

melihat detail dan relasi Opportunity;

memantau kualitas/kelengkapan data Contact;

menjalankan analitik workload PIC, status Opportunity, status Task, overdue Task, dan data terkait lainnya;

membuat dataset besar untuk pengujian;

melakukan sinkronisasi Opportunity Closed Won ke Accurate Online;

mencatat status sinkronisasi dan mencegah pembuatan transaksi duplikat.

2. Teknologi

Backend

Python

Flask

Requests

python-dotenv

SQLite untuk local application store

Frontend

HTML

CSS

JavaScript

Sistem eksternal

EspoCRM REST API

Accurate Online API / OAuth

3. Entity yang Digunakan

Project bekerja dengan beberapa entity CRM:

Account — data perusahaan/customer.

Contact — data kontak/person.

Opportunity — data peluang penjualan.

Task — pekerjaan yang dapat dikaitkan dengan Opportunity dan User/PIC.

Case — data kasus/tiket CRM.

User / PIC — pengguna yang dapat menjadi penanggung jawab aktivitas.

Relasi data digunakan agar dataset tidak berdiri sendiri. Contoh alur relasinya:

Account
   │
   ├── Contact
   │      │
   │      └── Opportunity
   │             │
   │             └── Task ── User/PIC
   │
   └── Opportunity

4. Struktur Project

Struktur utama yang digunakan aplikasi:

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

runtime/ digunakan untuk penyimpanan lokal aplikasi dan tidak perlu di-upload ke Git.

5. Fungsi File Utama

api.py

Lapisan komunikasi EspoCRM REST API.

Menangani antara lain:

CRUD Contact;

CRUD Account/Opportunity/Task/Case;

pencarian dan pagination;

pengambilan relationship;

pengambilan User/PIC;

advanced query untuk Opportunity dan Task;

generator dataset besar;

pembuatan dataset relasional.

web_app.py

Backend Flask dan route aplikasi web.

Menangani:

dashboard;

health check dan statistik;

data table server-side pagination;

detail entity;

relationship;

data quality scan;

analytics;

route Opportunity;

integrasi dan status Accurate;

trigger sinkronisasi Opportunity.

accurate_integration.py

Client untuk integrasi EspoCRM Opportunity ke Accurate Online.

Menangani:

mapping Opportunity ke Sales Invoice;

customer dan item mapping;

create invoice;

update invoice yang sudah pernah disinkronkan;

idempotency/duplicate prevention;

pencatatan status dan error sync;

penggunaan external ID dari transaksi Accurate.

accurate_oauth.py

Membantu proses OAuth Accurate Online, mengambil access token, memilih database Accurate, dan mendapatkan informasi koneksi/session.

app_store.py

Local persistent store berbasis SQLite untuk status sinkronisasi, state job, dan data pendukung aplikasi.

config.py

Konfigurasi koneksi EspoCRM dan authentication yang digunakan oleh api.py.

templates/index.html, static/css/style.css, static/js/app.js

Frontend dashboard dan web interface.

6. Prasyarat

Sebelum menjalankan project, pastikan sudah tersedia:

Windows.

Python 3.12 atau versi yang kompatibel dengan project.

Docker Desktop.

EspoCRM yang dapat diakses secara lokal.

Accurate Online Developer App apabila fitur Accurate digunakan.

Environment development yang digunakan project ini:

EspoCRM Web : http://localhost:8081
EspoCRM API : http://localhost:8081/api/v1
Flask App   : http://localhost:5000

7. Instalasi Project

7.1 Clone repository

Jika project belum ada di komputer:

git clone <URL-REPOSITORY>
cd espo-api-python-contact

Sesuaikan <URL-REPOSITORY> dengan repository GitHub project.

Jika project sudah ada di komputer, langsung masuk ke folder project.

cd "D:\Folder Tugas Phython Contat - BLTI\espo-api-python"

7.2 Buat virtual environment

python -m venv .venv

Aktifkan:

.\.venv\Scripts\Activate.ps1

Jika berhasil, prompt akan diawali dengan:

(.venv)

7.3 Install dependency

Upgrade pip:

python -m pip install --upgrade pip

Install dependency:

pip install -r requirements.txt

Jika requirements.txt belum tersedia pada checkout tertentu, dependency utama project adalah:

pip install Flask requests python-dotenv

8. Menyiapkan EspoCRM

Project membutuhkan EspoCRM aktif karena Python mengambil data melalui REST API.

Pada environment development yang digunakan:

cd "D:\espocrm_docker"
docker compose up -d

Periksa container:

docker ps

Kemudian buka:

http://localhost:8081

Pastikan EspoCRM dapat dibuka dan login berhasil.

Jika Docker/EspoCRM mati, request API Python akan gagal dengan error connection.

9. Konfigurasi EspoCRM

Konfigurasi EspoCRM diletakkan pada:

config.py

Base API pada environment development:

http://localhost:8081/api/v1

Authentication mengikuti konfigurasi yang digunakan oleh project (API Key apabila tersedia, atau Basic Authentication sesuai konfigurasi config.py).

Jangan memasukkan password atau API key asli ke repository publik.

10. Konfigurasi Accurate Online

Template konfigurasi tersedia di:

.env.example

Project lokal menggunakan file environment:

testumbrella.env

Buat dari template:

Copy-Item .env.example testumbrella.env

Kemudian isi nilai konfigurasi Accurate yang diperlukan.

Variabel yang digunakan project antara lain:

ACCURATE_CLIENT_ID=
ACCURATE_CLIENT_SECRET=
ACCURATE_REDIRECT_URI=http://localhost:5000/callback
ACCURATE_DATABASE_ALIAS=
ACCURATE_SCOPE=
ACCURATE_CUSTOMER_NO=
ACCURATE_SYNC_WORKER=false

Jangan menaruh nilai secret asli di README, GitHub, atau .env.example.

File credential/session lokal sudah dimasukkan ke .gitignore.

11. Menjalankan Aplikasi

Urutannya:

Terminal 1 — Jalankan EspoCRM

cd "D:\espocrm_docker"
docker compose up -d

Terminal 2 — Jalankan Python Web App

cd "D:\Folder Tugas Phython Contat - BLTI\espo-api-python"
.\.venv\Scripts\Activate.ps1
python web_app.py

Setelah Flask aktif, buka browser:

http://localhost:5000

12. Mengecek Koneksi

Health check:

http://localhost:5000/api/health

Endpoint ini mengecek apakah aplikasi Python dapat membaca data dari EspoCRM.

Statistik entity:

http://localhost:5000/api/stats

Status Accurate:

http://localhost:5000/api/accurate/status

13. Dashboard dan Analytics

Dashboard mengambil data dari backend Flask dan EspoCRM.

Analitik yang disiapkan project mencakup antara lain:

jumlah entity CRM;

distribusi stage/status Opportunity;

Opportunity berdasarkan periode;

workload PIC dari Opportunity dan Task;

status Task;

Task overdue;

informasi Case;

kualitas/kelengkapan Contact;

kondisi relationship data.

Untuk mengurangi beban saat dataset besar, analytics menggunakan cache dan pengambilan data di backend.

14. Data Table dan Pagination

Data table tidak memuat seluruh 10.000+ record ke browser.

Backend memakai parameter seperti:

page
page_size
search
sort
order

dan filter yang sesuai entity.

Contoh Opportunity dapat difilter berdasarkan:

Search;

Stage;

PIC/User;

Priority;

Account;

Contact;

Sort dan order.

Task mendukung filter seperti:

Search;

Status;

Priority;

PIC/User;

Parent Opportunity;

Overdue.

Pendekatan ini membuat browser hanya menerima data pada halaman yang sedang dibuka.

15. Data Besar 10.000+ Record

api.py menyediakan generator dataset besar untuk pengujian.

Fungsi utama:

generate_large_accounts()
generate_large_contacts()
generate_large_opportunities()
generate_large_tasks()
generate_large_crm_dataset()

Orchestrator dataset besar membuat data secara berurutan:

Account
   ↓
Contact
   ↓
Opportunity
   ↓
Task

Relationship menggunakan ID data yang sudah dibuat/tersedia sehingga data antar-module dapat saling berelasi.

Untuk pengujian awal, jangan langsung membuat 10.000 record. Gunakan jumlah kecil terlebih dahulu, misalnya:

python -c "import api; print(api.generate_large_crm_dataset(account_count=100, contact_count=100, opportunity_count=100, task_count=100))"

Setelah alurnya sudah dipastikan benar, jumlah dapat dinaikkan sesuai kebutuhan pengujian.

Contoh target sesuai requirement:

python -c "import api; print(api.generate_large_crm_dataset(account_count=10000, contact_count=10000, opportunity_count=10000, task_count=10000))"

Pembuatan dataset sebesar ini dapat memerlukan waktu dan request API dalam jumlah besar.

Task membutuhkan User/PIC aktif pada EspoCRM karena assignedUser digunakan dalam data Task.

16. Integrasi Opportunity → Accurate

Alur sinkronisasi:

Opportunity EspoCRM
        │
        ▼
Stage = Closed Won?
        │
        ▼
Validasi data
        │
        ▼
Mapping Customer / Item / Amount / Date
        │
        ▼
Accurate Sales Invoice
        │
        ▼
Simpan external ID + status sync

Mapping utama meliputi:

Opportunity ID → identitas sumber/external reference;

Opportunity Name → reference/description;

Account/customer → customer Accurate;

item Opportunity/default item → item Accurate;

Amount → unit price/total sesuai detail yang dikirim;

Close Date → transaction date;

currency → nilai currency yang tersedia dari Opportunity/configuration.

17. Aturan Sinkronisasi Accurate

Untuk Opportunity yang belum pernah disinkronkan:

belum ada external ID
        ↓
CREATE Sales Invoice

Untuk Opportunity yang sama dan tidak berubah:

sudah pernah sync
+ data tidak berubah
        ↓
SKIPPED

Untuk Opportunity yang sudah pernah disinkronkan tetapi nilainya berubah:

sudah pernah sync
+ data berubah
        ↓
UPDATE Sales Invoice

Jika validasi atau request gagal:

FAILED / FAILED_VALIDATION

Status dan error dicatat pada local application store.

Project juga mempertahankan detail ID saat melakukan update invoice agar detail yang sudah ada diperbarui, bukan dibuat sebagai line baru yang menyebabkan total berlipat.

18. Automatic Sync dan Worker

Project memiliki dua mekanisme:

Mutation route

Ketika Opportunity diperbarui melalui route aplikasi Python dan hasil akhirnya menjadi:

Closed Won

aplikasi dapat langsung memanggil sinkronisasi Accurate untuk Opportunity tersebut.

Background worker

Worker scanning Opportunity Closed Won historis tersedia tetapi OFF secara default:

ACCURATE_SYNC_WORKER=false

Worker tidak disarankan dinyalakan sembarangan pada dataset besar karena dapat memproses Opportunity lama yang sebenarnya tidak dimaksudkan untuk dikirim ke Accurate.

19. OAuth Accurate

Jika koneksi Accurate belum tersedia, route utama OAuth adalah:

http://localhost:5000/accurate/connect

Callback yang digunakan:

http://localhost:5000/callback

Callback tersebut harus sama dengan callback yang didaftarkan pada Accurate Developer.

Setelah proses OAuth selesai, status koneksi dapat diperiksa melalui:

http://localhost:5000/api/accurate/status

20. Troubleshooting

A. EspoCRM tidak terhubung

Cek Docker:

docker ps

Jika perlu jalankan lagi:

cd "D:\espocrm_docker"
docker compose up -d

Lalu tes:

http://localhost:8081

B. Flask tidak mau start

Pastikan virtual environment aktif:

.\.venv\Scripts\Activate.ps1

Kemudian:

python web_app.py

C. Port 5000 sudah digunakan

Hentikan Flask instance lama dengan:

CTRL + C

Lalu jalankan kembali:

python web_app.py

D. Accurate belum terhubung

Periksa:

http://localhost:5000/api/accurate/status

Kemudian cek konfigurasi:

testumbrella.env tersedia;

Client ID/Client Secret benar;

Redirect URI benar;

database alias benar;

scope sesuai permission aplikasi;

customer/item yang dipetakan tersedia di Accurate.

E. Task gagal dibuat

Pastikan EspoCRM memiliki User/PIC aktif.

Task membutuhkan assignedUser sehingga generator Task tidak dapat bekerja jika tidak ada User/PIC yang dapat digunakan.

F. Detail Opportunity bermasalah

Detail Opportunity dirancang agar data utama tetap bisa ditampilkan walaupun salah satu relationship endpoint tidak tersedia pada instance EspoCRM.

Jika terjadi error, cek endpoint dan relationship yang gagal dari response Flask/API.

21. Keamanan

Jangan pernah commit atau upload file yang berisi:

testumbrella.env
accurate_token.json
accurate_connection.json
accurate_sync.json
accurate_oauth_debug.txt

Jangan menaruh:

Client Secret;

Access Token;

Session ID;

password EspoCRM;

API Key

ke README atau repository publik.

22. Git / GitHub

Cek perubahan:

git status

Tambahkan file project yang memang berubah:

git add <nama-file>

Commit:

git commit -m "Update application"

Push:

git push

Cek kembali:

git status

Kondisi bersih ditandai dengan:

nothing to commit, working tree clean

Jangan menggunakan git add . tanpa memeriksa status dan .gitignore, terutama karena project mempunyai file environment dan credential lokal.

23. Quick Start

Untuk menjalankan project sehari-hari:

Terminal 1

cd "D:\espocrm_docker"
docker compose up -d

Terminal 2

cd "D:\Folder Tugas Phython Contat - BLTI\espo-api-python"
.\.venv\Scripts\Activate.ps1
python web_app.py

Buka:

http://localhost:5000

Status Project

Project ini berfungsi sebagai prototype/internship application untuk menunjukkan:

pengelolaan data CRM dengan jumlah besar;

relationship antar-module EspoCRM;

server-side pagination dan filtering;

dashboard dan analytics;

data quality monitoring;

pembuatan dataset besar untuk pengujian;

integrasi Opportunity EspoCRM → Accurate Online;

idempotency, update sync, dan error handling.
