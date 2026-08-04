# check_hash.py
import asyncio
import getpass
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    DATABASE_URL = os.getenv("DATABASE_URL")
    engine = create_async_engine(DATABASE_URL)
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT id, username, password_hash FROM iam_user WHERE username = 'admin'"))
        row = result.fetchone()
        if row:
            user_id, username, pwd_hash = row[0], row[1], row[2]
            print(f"User ID: {user_id}, Username: {username}")

            if not pwd_hash:
                print("Hash: KOSONG / NULL di database!")
                return

            print(f"Panjang hash: {len(pwd_hash)} karakter (harus 60 untuk bcrypt)")
            print(f"Prefix hash: {pwd_hash[:7]}")  # cukup untuk lihat $2b$12$ tanpa expose hash penuh

            # Attempt to decode rounds from hash
            try:
                # bcrypt hash format setelah split('$'): ['', '2b', '12', 'saltandhash']
                parts = pwd_hash.split('$')
                if len(parts) >= 3:
                    rounds = int(parts[2])
                    print(f"Rounds: {rounds}")
            except Exception:
                print("Tidak bisa parse rounds dari hash (format hash mungkin tidak valid)")

            # Verifikasi password langsung di sini, tanpa perlu copy-paste hash ke tempat lain
            try:
                from passlib.hash import bcrypt as passlib_bcrypt
                pwd = getpass.getpass("Masukkan password yang mau dicek (mis. Admin123!): ")
                is_valid = passlib_bcrypt.verify(pwd, pwd_hash)
                print(f"Hasil verifikasi (passlib): {is_valid}")
            except Exception as e:
                print(f"Verifikasi passlib gagal dengan error: {e}")

            # Verifikasi ulang pakai library bcrypt langsung, buat cross-check di luar passlib
            try:
                import bcrypt as bcrypt_lib
                is_valid_raw = bcrypt_lib.checkpw(pwd.encode("utf-8"), pwd_hash.encode("utf-8"))
                print(f"Hasil verifikasi (bcrypt langsung): {is_valid_raw}")
            except Exception as e:
                print(f"Verifikasi bcrypt langsung gagal dengan error: {e}")
        else:
            print("User not found")

if __name__ == "__main__":
    asyncio.run(main())
