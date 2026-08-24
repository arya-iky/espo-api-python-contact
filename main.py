"""
=========================================
ESPOCRM CONTACT MANAGER
Main Program
=========================================

File ini hanya digunakan untuk menjalankan aplikasi.
Seluruh proses REST API berada di api.py.
Seluruh tampilan GUI berada di dashboard.py.
"""

from dashboard import Dashboard


def main():
    """
    Menjalankan Dashboard Utama.
    """
    Dashboard()


if __name__ == "__main__":
    main()