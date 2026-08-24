# Dokumentasi: Relational Data EspoCRM (Module: Contact)

## 1. Ringkasan

Project ini merupakan implementasi **Task 4 — Relational Data EspoCRM** dengan menggunakan **Python**, **Tkinter**, dan **EspoCRM REST API**.

Project menampilkan data **Contact** dari EspoCRM beserta relasinya dengan:

* **Account**
* **Opportunity**
* **Case**

Aplikasi menyediakan dashboard untuk menampilkan data Contact, pencarian, pagination, detail Contact, serta informasi relationship yang terhubung dengan Contact yang dipilih.

## 2. Relasi yang Digunakan

```text
Contact (1)
├── Account (banyak/sesuai relasi EspoCRM)
├── Opportunity (banyak)
└── Case (banyak)
```

Relasi tersebut diakses melalui relationship endpoint bawaan EspoCRM.

Contoh:

```text
Contact/{id}/accounts
Contact/{id}/opportunities
Contact/{id}/cases
```

Ketika pengguna memilih satu Contact pada dashboard, aplikasi mengambil relationship dari Contact tersebut dan menampilkannya pada bagian detail.

## 3. Arsitektur

```text
Python + Tkinter
       |
       v
dashboard.py
       |
       v
api.py
       |
       v
EspoCRM REST API
       |
       v
EspoCRM Server
http://localhost:8081
```

### Penjelasan

**main.py**

Merupakan entry point aplikasi dan menjalankan dashboard.

**dashboard.py**

Menangani tampilan dashboard, tabel Contact, pagination, search, detail Contact, relationship, CRUD action, export CSV, serta tombol restore.

**contact_form.py**

Menangani form untuk menambahkan dan mengedit Contact.

**api.py**

Menangani seluruh komunikasi antara aplikasi Python dengan EspoCRM REST API.

**config.py**

Menyimpan konfigurasi server dan akun EspoCRM yang digunakan oleh aplikasi.

**config_example.py**

Template konfigurasi yang dapat digunakan sebagai dasar untuk membuat `config.py`.

## 4. Authentication

Project menggunakan **Basic Authentication** untuk mengakses EspoCRM REST API.

Konfigurasi disimpan pada `config.py`.

```python
BASE_URL = "http://localhost:8081/api/v1"

USERNAME = "admin"
PASSWORD = "admin123"
```

Untuk alasan keamanan, file `config.py` tidak digunakan sebagai file konfigurasi publik.

Sebagai gantinya, repository menyediakan:

```text
config_example.py
```

Pengguna dapat membuat `config.py` sendiri berdasarkan file tersebut.

## 5. Endpoint API EspoCRM yang Digunakan

| Fungsi                            | Endpoint EspoCRM                               | Method |
| --------------------------------- | ---------------------------------------------- | ------ |
| Ambil daftar Contact              | `/api/v1/Contact?maxSize=&offset=&textFilter=` | GET    |
| Ambil Contact berdasarkan ID      | `/api/v1/Contact/{id}`                         | GET    |
| Tambah Contact                    | `/api/v1/Contact`                              | POST   |
| Update Contact                    | `/api/v1/Contact/{id}`                         | PUT    |
| Hapus Contact                     | `/api/v1/Contact/{id}`                         | DELETE |
| Ambil Account terkait Contact     | `/api/v1/Contact/{id}/accounts`                | GET    |
| Ambil Opportunity terkait Contact | `/api/v1/Contact/{id}/opportunities`           | GET    |
| Ambil Case terkait Contact        | `/api/v1/Contact/{id}/cases`                   | GET    |

### Parameter Contact

Untuk daftar Contact, aplikasi menggunakan parameter:

```text
maxSize
offset
textFilter
orderBy
order
```

Contoh request:

```text
GET /api/v1/Contact?offset=0&maxSize=20&textFilter=
```

Pagination menggunakan kombinasi `offset` dan `maxSize`.

## 6. Fitur yang Diimplementasikan

### Contact

* Menampilkan daftar Contact dari EspoCRM
* Search Contact
* Pagination Contact
* Melihat detail Contact
* Add Contact
* Edit Contact
* Delete Contact
* Restore Contact
* Export Contact ke CSV
* Refresh data

### Relationship

* Melihat Account yang terhubung
* Melihat Opportunity yang terhubung
* Melihat Case yang terhubung
* Search relationship
* Relationship cache
* Relationship count

### Keyboard Shortcut

| Shortcut   | Fungsi                                |
| ---------- | ------------------------------------- |
| `F5`       | Refresh data                          |
| `Ctrl + F` | Focus ke Search Contact               |
| `Ctrl + Z` | Restore Contact terakhir yang dihapus |
| `Escape`   | Kembali ke detail Contact             |

## 7. Pagination

Pagination digunakan agar data Contact tidak ditampilkan seluruhnya dalam satu tampilan.

Ukuran halaman aplikasi:

```text
20 Contact per halaman
```

Contoh:

```text
Page 1 / 2
Page 2 / 2
```

Aplikasi mengirimkan parameter:

```text
offset=0
maxSize=20
```

untuk halaman pertama.

Halaman berikutnya menggunakan:

```text
offset=20
maxSize=20
```

Dengan demikian, jumlah data yang ditampilkan pada satu halaman tetap terbatas dan pengguna dapat berpindah halaman menggunakan tombol **Previous** dan **Next**.

## 8. Alur Kerja Dashboard

1. User menjalankan `main.py`.
2. Aplikasi Python menjalankan dashboard Tkinter.
3. Dashboard memanggil `get_contacts()` dari `api.py`.
4. `api.py` mengirim request ke EspoCRM REST API.
5. EspoCRM mengembalikan data Contact.
6. Data ditampilkan pada tabel Contact.
7. User dapat melakukan pencarian atau berpindah halaman.
8. User memilih salah satu Contact.
9. Dashboard mengambil detail Contact berdasarkan ID.
10. User dapat memilih relationship:

    * Contact
    * Account
    * Opportunity
    * Case
11. Dashboard mengambil data relationship menggunakan endpoint EspoCRM.
12. Relationship ditampilkan pada panel detail.

## 9. Alur Detail Relationship

Contoh ketika user memilih Contact:

```text
User memilih Contact
        |
        v
GET /api/v1/Contact/{id}
        |
        v
Menampilkan detail Contact
        |
        +----------------------+
        |          |           |
        v          v           v
   /accounts  /opportunities  /cases
        |          |           |
        v          v           v
    Account   Opportunity      Case
```

Relationship tidak dimuat sekaligus ketika aplikasi pertama kali dibuka.

Data relationship dimuat ketika user memilih relationship tertentu pada panel detail.

## 10. Contoh Response API

### Request Contact

```text
GET /api/v1/Contact?offset=0&maxSize=20
```

### Response

```json
{
  "total": 11,
  "list": [
    {
      "id": "6a892697e3a607eb2",
      "name": "San Last Nai",
      "firstName": "San",
      "lastName": "Last Nai",
      "emailAddress": "san@example.com",
      "phoneNumber": "+628123456789",
      "createdAt": "2026-08-20 10:00:00",
      "modifiedAt": "2026-08-20 10:00:00"
    }
  ]
}
```

Nilai `total` digunakan oleh dashboard untuk menentukan jumlah halaman.

## 11. Validasi Contact

Project melakukan validasi sebelum data dikirim ke EspoCRM.

### First Name

First Name wajib diisi.

### Last Name

Last Name wajib diisi.

### Email

Email harus menggunakan format email yang valid.

Contoh:

```text
user@example.com
```

### Phone

Nomor telepon harus menggunakan karakter yang didukung oleh EspoCRM.

Contoh format yang digunakan:

```text
+628123456789
+6281234567890
+62123456789
```

Format dengan kode negara `+62` digunakan dalam pengujian karena sebelumnya ditemukan bahwa input nomor telepon yang tidak sesuai format menyebabkan EspoCRM mengembalikan:

```text
Status: 400
validationFailure
field: phoneNumber
```

## 12. Cara Menjalankan Project

### 1. Pastikan EspoCRM berjalan

Pastikan Docker/EspoCRM sedang berjalan dan dapat diakses melalui:

```text
http://localhost:8081
```

REST API digunakan melalui:

```text
http://localhost:8081/api/v1
```

### 2. Clone Repository

```powershell
git clone https://github.com/arya-iky/espo-api-python-contact.git
```

Masuk ke folder project:

```powershell
cd espo-api-python-contact
```

### 3. Pastikan Python Terinstall

Project menggunakan Python.

Versi Python yang digunakan saat pengembangan:

```text
Python 3.12.10
```

Cek versi Python:

```powershell
python --version
```

### 4. Install Dependency

Install library yang diperlukan:

```powershell
pip install -r requirements
```

Apabila file dependency pada project menggunakan nama `requirements.txt`, gunakan:

```powershell
pip install -r requirements.txt
```

Dependency utama yang digunakan adalah:

```text
requests
```

### 5. Buat File `config.py`

Repository menyediakan:

```text
config_example.py
```

Buat file:

```text
config.py
```

Kemudian sesuaikan konfigurasi:

```python
BASE_URL = "http://localhost:8081/api/v1"

USERNAME = "admin"
PASSWORD = "admin123"
```

Sesuaikan `USERNAME` dan `PASSWORD` dengan akun administrator EspoCRM yang digunakan.

### 6. Jalankan Project

Gunakan:

```powershell
python main.py
```

Dashboard Tkinter akan terbuka.

## 13. Pengujian Relationship

Untuk melakukan pengujian, data EspoCRM harus memiliki:

```text
Contact
Account
Opportunity
Case
```

Salah satu Contact kemudian dihubungkan dengan Account, Opportunity, dan Case.

Pengujian dilakukan dengan alur:

```text
EspoCRM
   |
   +-- Contact
   |
   +-- Account
   |
   +-- Opportunity
   |
   +-- Case
          |
          v
      Python Dashboard
          |
          v
      Pilih Contact
          |
          v
      Lihat Relationship
```

Setelah memilih Contact pada dashboard, user dapat membuka:

```text
Accounts
Opportunities
Cases
```

dan menggunakan fitur search relationship untuk mencari data yang berhubungan dengan Contact tersebut.

## 14. Struktur Project

```text
espo-api-python-contact/
│
├── .gitignore
├── README.md
├── DOCUMENTATION.md
├── api.py
├── config_example.py
├── contact_form.py
├── dashboard.py
├── main.py
├── requirements
└── test_relationship.py
```

## 15. Repository

Source code project tersedia pada:

```text
https://github.com/arya-iky/espo-api-python-contact
```
