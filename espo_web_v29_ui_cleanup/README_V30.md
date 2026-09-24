V30 - Contact Quality Definition Fix

Perubahan:
- Data Quality hanya menghitung field inti Contact: firstName, lastName, emailAddress, phoneNumber, accountId.
- Field metadata opsional (title, city, country, address, description, middleName, postal code) tidak lagi mempengaruhi skor.
- 100% field inti terisi = Lengkap/hijau.
- 60-99% = Kurang/kuning.
- <60% = Tidak komplet/merah.
- Cache quality lama otomatis dibersihkan sekali saat schema version berubah.
- Tidak mengubah api.py.
