# Panduan Pemakaian Program Banking Gateway & Escrow Simulator

Dokumen ini menjelaskan cara menjalankan program dan contoh input untuk setiap menu yang tersedia di aplikasi.

## 1. Cara Menjalankan Program

1. Buka terminal di folder project.
2. Jalankan perintah:

```powershell
python bank_teller.py
```

3. Akan muncul menu utama seperti ini:

```text
1. Register merchant
2. Create customer account
3. Deposit
4. Withdraw
5. Transfer between accounts
6. External bank transfer
7. Escrow hold
8. Escrow release
9. Visa endpoint simulation
10. Quantum queue processing
11. Settlement report
12. Show accounts
13. Show merchants
14. Approve merchant account
15. Review pending approvals
16. Admin approve authorization
17. SWIFT international transfer
18. SWIFT settlement queue processing
19. Generate SWIFT status report
20. Generate SWIFT advice message
21. Export SWIFT XML
22. Show SWIFT messages
23. Approve SWIFT message
24. Cancel SWIFT message
25. Reverse SWIFT message
26. UETR tracking dashboard
27. Search UETR
28. List UETR tracking
29. Export UETR XML
30. Export UETR report
0. Exit
```

4. Ketik angka menu lalu tekan Enter.
5. Setelah selesai, program akan kembali ke menu utama. Tekan Enter untuk lanjut.

---

## 2. Contoh Penggunaan per Menu

### Menu 1 — Register Merchant
Gunakan untuk mendaftarkan merchant baru.

Contoh input:

```text
Merchant name: PT Sinar Digital
Merchant code (optional): SDG001
Currency (USD, EUR, GBP, JPY, IDR): IDR
Initial deposit: 5000000
API key (optional, leave blank to auto-generate):
API secret (optional, leave blank to auto-generate):
```

Hasil yang diharapkan:
- Merchant berhasil dibuat.
- Status merchant biasanya masih pending approval.

---

### Menu 2 — Create Customer Account
Gunakan untuk membuat akun nasabah baru.

Contoh input:

```text
Customer name: Budi Santoso
Currency (USD, EUR, GBP, JPY, IDR): USD
Initial deposit: 1000
```

Hasil yang diharapkan:
- Akun baru dibuat dengan ID akun.

---

### Menu 3 — Deposit
Gunakan untuk menambah saldo akun.

Contoh input:

```text
Account ID: 1
Amount: 2500
Deposit currency: USD
```

Hasil yang diharapkan:
- Saldo akun bertambah.
- Akan muncul receipt/struk transaksi.

---

### Menu 4 — Withdraw
Gunakan untuk menarik saldo dari akun.

Contoh input:

```text
Account ID: 1
Amount: 500
```

Hasil yang diharapkan:
- Saldo akun berkurang.

---

### Menu 5 — Transfer Between Accounts
Gunakan untuk transfer antar akun internal.

Contoh input:

```text
From account ID: 1
To account ID: 2
Amount: 300
Currency: USD
```

Hasil yang diharapkan:
- Saldo dari akun sumber berkurang.
- Saldo ke akun tujuan bertambah.

---

### Menu 6 — External Bank Transfer
Gunakan untuk simulasi transfer ke bank luar sistem.

Contoh input:

```text
From account ID: 1
Target bank name: Bank Luar Negeri
Target account number: 8801234567
Amount: 750
Currency: USD
```

Hasil yang diharapkan:
- Transfer dibuat dalam status antrian / simulasi eksternal.

---

### Menu 7 — Escrow Hold
Gunakan untuk menahan dana dalam escrow.

Contoh input:

```text
Account ID: 1
Amount: 2000
Escrow reference: ORDER-001
```

Hasil yang diharapkan:
- Dana ditahan di escrow.
- Akan muncul ID escrow dan receipt.

---

### Menu 8 — Escrow Release
Gunakan untuk melepaskan dana escrow yang sudah ditahan.

Contoh input:

```text
Escrow ID: 1
```

Hasil yang diharapkan:
- Dana escrow dilepas ke akun terkait.

---

### Menu 9 — Visa Endpoint Simulation
Gunakan untuk mensimulasikan transaksi pembayaran Visa.

Contoh input:

```text
Customer account ID: 1
Merchant account ID: 1
Merchant API key (optional):
Request HMAC signature (optional):
Amount: 150
Currency: USD
```

Hasil yang diharapkan:
- Proses pembayaran Visa selesai dan menampilkan receipt.

---

### Menu 10 — Quantum Queue Processing
Gunakan untuk memproses antrian tugas kuantum.

Contoh input:
- Tidak perlu input tambahan.

Hasil yang diharapkan:
- Antrian quantum diproses.

---

### Menu 11 — Settlement Report
Gunakan untuk membuat laporan settlement.

Contoh input:

```text
Report type: DAILY
Total settlement amount: 5000000
Currency: USD
```

Catatan:
- Jika dikosongkan, default report type adalah DAILY.

---

### Menu 12 — Show Accounts
Menampilkan daftar akun yang sudah dibuat.

Contoh output:

```text
ID  | Name                 | Currency | Balance        | Created
```

---

### Menu 13 — Show Merchants
Menampilkan daftar merchant.

Contoh output:

```text
ID  | Merchant Name         | Code        | Currency | Balance        | Created
```

---

### Menu 14 — Approve Merchant Account
Menyetujui merchant yang masih pending.

Contoh input:

```text
Merchant ID: 1
```

Hasil yang diharapkan:
- Merchant berubah status approved.

---

### Menu 15 — Review Pending Approvals
Melihat transaksi atau escrow yang masih menunggu persetujuan.

Contoh output:

```text
Visa transactions pending approval:
Escrow settlements pending approval:
```

---

### Menu 16 — Admin Approve Authorization
Digunakan untuk menyetujui atau menolak transaksi tertentu secara manual.

Contoh input:

```text
Approval table (visa_transactions or escrow_settlements): visa_transactions
Transaction TRN: TRN123
Approve? (y/n): y
```

---

### Menu 17 — SWIFT International Transfer
Gunakan untuk simulasi transfer internasional SWIFT.

Contoh input:

```text
Sender BIC: BANKUS33
Receiver BIC: BANKSG33
Debtor name: Budi Santoso
Creditor name: PT Global Supply
Amount: 200000000
Currency: USD
Payment purpose (optional): Invoice payment
```

Hasil yang diharapkan:
- Pesan SWIFT dibuat.
- Akan muncul TRN dan UETR.

---

### Menu 18 — SWIFT Settlement Queue Processing
Memproses antrian settlement SWIFT.

Contoh input:
- Tidak perlu input tambahan.

---

### Menu 19 — Generate SWIFT Status Report
Membuat laporan status untuk TRN SWIFT tertentu.

Contoh input:

```text
SWIFT TRN: TRN123
Status reason: Payment processed successfully
```

---

### Menu 20 — Generate SWIFT Advice Message
Membuat pesan advice SWIFT.

Contoh input:

```text
SWIFT TRN: TRN123
Advice message: Please confirm settlement completion
```

---

### Menu 21 — Export SWIFT XML
Mengekspor XML SWIFT ke file.

Contoh input:

```text
SWIFT TRN: TRN123
File path: swift_output.xml
```

Hasil yang diharapkan:
- File XML dibuat di lokasi yang ditentukan.

---

### Menu 22 — Show SWIFT Messages
Menampilkan daftar pesan SWIFT yang tersimpan.

Contoh input:

```text
Status filter (optional): PENDING
```

Jika dikosongkan, program menampilkan semua pesan.

---

### Menu 23 — Approve SWIFT Message
Menyetujui pesan SWIFT.

Contoh input:

```text
SWIFT TRN: TRN123
Approve? (y/n): y
```

---

### Menu 24 — Cancel SWIFT Message
Membatalkan pesan SWIFT.

Contoh input:

```text
SWIFT TRN: TRN123
```

---

### Menu 25 — Reverse SWIFT Message
Mengembalikan / membalik transaksi SWIFT.

Contoh input:

```text
SWIFT TRN: TRN123
```

---

### Menu 26 — UETR Tracking Dashboard
Membuat tracking UETR lengkap dengan simulasi rute.

Contoh input:

```text
Amount: 50000
Currency: USD
Sender BIC: BANKUS33
Receiver BIC: BANKSG33
Debtor name: Budi Santoso
Creditor name: PT Global Supply
```

Hasil yang diharapkan:
- UETR dibuat.
- Tampilkan route dan progress tracking.

---

### Menu 27 — Search UETR
Mencari data tracking berdasarkan UETR, TRN, BIC, atau status.

Contoh input:

```text
Search by UETR / TRN / BIC / status: UETR123
```

---

### Menu 28 — List UETR Tracking
Menampilkan seluruh data UETR tracking yang tersimpan.

Contoh input:
- Tidak perlu input tambahan.

---

### Menu 29 — Export UETR XML
Mengekspor data UETR ke file XML.

Contoh input:

```text
UETR: UETR123
Output file path: uetr_export.xml
```

---

### Menu 30 — Export UETR Report
Mengekspor laporan UETR ke file teks.

Contoh input:

```text
UETR: UETR123
Output file path: uetr_report.txt
```

---

## 3. Contoh Alur Sederhana untuk Demo

Berikut contoh urutan yang cocok untuk mencoba program dari awal:

1. Pilih menu 2 → buat akun nasabah.
2. Pilih menu 1 → buat merchant.
3. Pilih menu 14 → approve merchant.
4. Pilih menu 3 → deposit saldo.
5. Pilih menu 5 → transfer antar akun.
6. Pilih menu 7 → hold escrow.
7. Pilih menu 17 → buat SWIFT transfer.
8. Pilih menu 22 → lihat SWIFT messages.
9. Pilih menu 26 → lihat UETR dashboard.

---

## 4. Tips Praktis

- Gunakan angka yang valid untuk ID akun, merchant, dan amount.
- Untuk field yang opsional, cukup tekan Enter.
- Jika ingin memakai default nilai, tekan Enter pada prompt yang menampilkan default.
- Untuk demo, gunakan currency USD agar hasil lebih mudah dibaca.

---

## 5. Keluar dari Program

Pilih menu:

```text
0
```

Maka program akan keluar dengan pesan:

```text
Exiting banking gateway simulation.
```
