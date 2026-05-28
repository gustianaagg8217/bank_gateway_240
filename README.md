# Banking Gateway Simulator

Simulasi gateway perbankan profesional berbasis Python dan SQLite.

## Fitur utama

- Akun pelanggan dan merchant dengan multi-currency
- Deposit, withdrawal, transfer domestic, dan transfer eksternal
- Escrow hold / release dengan approval admin untuk jumlah besar
- Simulasi endpoint Visa dengan merchant API key dan HMAC signature
- Antrian quantum processing untuk workflow batch
- Settlement report XML generation
- Merchant approval dan otorisasi transaksi pending
- Audit log immutable untuk setiap transaksi

## Cara menjalankan

1. Buka folder `E:\Basecamp\Point_getway`
2. Jalankan:

```powershell
python bank_teller.py
```

Database akan dibuat secara otomatis di `point_getway.db`.

## Catatan

- Merchant baru dibuat dalam status `pending` dan harus disetujui melalui menu admin.
- Transaksi Visa bernilai tinggi dapat diproses dalam status `pending` dan disetujui melalui menu admin.
- API key merchant dapat digunakan untuk mensimulasikan koneksi gateway yang terautentikasi.
