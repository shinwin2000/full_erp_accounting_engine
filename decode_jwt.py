"""
Decode payload JWT (tanpa verifikasi signature) supaya bisa lihat isi klaim
seperti roles, permissions, legal_entity_id, dll.

Usage:
    python decode_jwt.py "<access_token_di_sini>"
"""
import base64
import json
import sys


def decode_jwt_payload(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Token JWT tidak valid (harus 3 bagian dipisah titik)")
    payload_b64 = parts[1]
    # tambahkan padding base64 kalau perlu
    padding = "=" * (-len(payload_b64) % 4)
    payload_json = base64.urlsafe_b64decode(payload_b64 + padding)
    return json.loads(payload_json)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python decode_jwt.py <access_token>")
        sys.exit(1)
    token = sys.argv[1]
    payload = decode_jwt_payload(token)
    print(json.dumps(payload, indent=2))

    print("\n=== Ringkasan ===")
    print(f"  sub (user_id)     : {payload.get('sub')}")
    print(f"  username          : {payload.get('username')}")
    print(f"  roles             : {payload.get('roles')}")
    print(f"  permissions       : {payload.get('permissions')}")
    print(f"  legal_entity_id   : {payload.get('legal_entity_id')}")
    if not payload.get("roles") and not payload.get("permissions"):
        print("\n  >> PERINGATAN: roles & permissions KOSONG.")
        print("  >> Ini kemungkinan besar penyebab semua endpoint balikin 403 Forbidden,")
        print("  >> walau user berstatus is_superuser=True di database.")
