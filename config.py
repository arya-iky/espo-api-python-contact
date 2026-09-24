"""
=========================================
ESPOCRM CONFIGURATION
=========================================

Seluruh konfigurasi aplikasi disimpan di file ini.

Jika URL server atau kredensial EspoCRM berubah,
cukup ubah konfigurasi di file ini.
"""

# =========================================
# ESPOCRM SERVER
# =========================================

BASE_URL = "http://localhost:8081/api/v1"


# =========================================
# LOGIN ADMIN ESPOCRM
# =========================================

USERNAME = "admin"
PASSWORD = "admin123"


# =========================================
# API CONFIGURATION
# =========================================

# Timeout request ke EspoCRM dalam detik.
REQUEST_TIMEOUT = 15


# =========================================
# HTTP HEADERS
# =========================================

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json"
}