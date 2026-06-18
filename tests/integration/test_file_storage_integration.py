#!/usr/bin/env python3
"""
Integration: File Storage (S3/Minio)
Menguji upload, download, delete file, serta integrity hash dan retention policy.
"""

from __future__ import annotations

import hashlib

import pytest

from infrastructure.file_storage.file_integrity_hasher import FileIntegrityHasher
from infrastructure.file_storage.retention_policy_enforcer import RetentionPolicyEnforcer
from infrastructure.file_storage.s3_adapter import S3FileStorage


@pytest.fixture
def file_storage():
    # Gunakan Minio local atau S3 mock
    try:
        storage = S3FileStorage(
            endpoint_url="http://localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            bucket="test-bucket",
            secure=False,
        )
        storage.create_bucket()
        return storage
    except Exception:
        pytest.skip("Minio/S3 tidak tersedia")


def test_upload_download_file(file_storage):
    content = b"Hello, ERP!"
    key = "test/file1.txt"
    file_storage.upload(key, content)

    downloaded = file_storage.download(key)
    assert downloaded == content

    # Cek metadata
    metadata = file_storage.head_object(key)
    assert metadata["size"] == len(content)


def test_file_integrity_hash(file_storage):
    content = b"Important document"
    key = "test/integrity.txt"
    file_storage.upload(key, content)

    hasher = FileIntegrityHasher(file_storage)
    stored_hash = hasher.get_hash(key)
    computed_hash = hashlib.sha256(content).hexdigest()
    assert stored_hash == computed_hash

    # Verifikasi
    assert hasher.verify(key) is True


def test_retention_policy(file_storage):
    policy = RetentionPolicyEnforcer(file_storage, retention_days=7)
    # Upload file dengan tanggal lama
    old_key = "test/old.txt"
    file_storage.upload(old_key, b"old", metadata={"upload_date": "2025-01-01"})
    policy.enforce()
    # File lama harus sudah dihapus
    assert file_storage.exists(old_key) is False
