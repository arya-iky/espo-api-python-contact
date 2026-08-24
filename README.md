# EspoCRM Contact Relational Dashboard

Project ini merupakan implementasi **Task 4 — Relational Data EspoCRM**, yang menampilkan data **Contact** beserta relasinya dengan **Account, Opportunity, dan Case** menggunakan **Python, Tkinter, dan EspoCRM REST API**.

## Cara Menjalankan

### 1. Clone Repository

```bash
git clone https://github.com/arya-iky/espo-api-python-contact.git
cd espo-api-python-contact
```

### 2. Install Dependency

Pastikan Python sudah terpasang, lalu jalankan:

```bash
pip install -r requirements
```

### 3. Konfigurasi EspoCRM

Salin `config_example.py` menjadi `config.py`:

```bash
copy config_example.py config.py
```

Kemudian buka `config.py` dan sesuaikan konfigurasi EspoCRM:

```python
BASE_URL = "http://localhost:8081/api/v1"

USERNAME = "admin"
PASSWORD = "admin123"
```

Pastikan **EspoCRM sedang berjalan** pada:

```text
http://localhost:8081
```

### 4. Jalankan Aplikasi

```bash
python main.py
```

Dashboard Contact akan terbuka menggunakan Tkinter.

### 5. Fitur Utama

Aplikasi menyediakan:

* Menampilkan daftar Contact
* Search Contact
* Pagination
* Detail Contact
* Relasi Account
* Relasi Opportunity
* Relasi Case
* Search Relationship
* Add Contact
* Edit Contact
* Delete Contact
* Restore Contact
* Export CSV
* Refresh Data

Repository:

```text
https://github.com/arya-iky/espo-api-python-contact
```
