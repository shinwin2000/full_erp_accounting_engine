#!/usr/bin/env python3
"""
Module: file_integrity_hasher.py
Layer: Infrastructure (File Storage)
Responsibility: Menyediakan fungsi hashing untuk integritas file menggunakan
               SHA-256. Digunakan untuk memverifikasi bahwa file tidak berubah
               sejak pertama kali diupload. Juga mendukung chunked hashing
               untuk file besar.
"""

from __future__ import annotations

import hashlib
import logging
from typing import BinaryIO

logger = logging.getLogger(__name__)

# ============================================================================
# FILE INTEGRITY HASHER
# ============================================================================


class FileIntegrityHasher:
    """
    Hasher untuk integritas file.

    Fitur:
    - SHA-256 hashing untuk file content
    - Chunked hashing untuk file besar
    - Hash verification
    - Multiple algorithm support (SHA-256 default)
    """

    def __init__(self, algorithm: str = "sha256"):
        self.algorithm = algorithm
        self._chunk_size = 8192  # 8KB chunks

    def compute_hash(self, content: bytes) -> str:
        """
        Compute hash of bytes content.
        """
        if self.algorithm == "sha256":
            return hashlib.sha256(content).hexdigest()
        elif self.algorithm == "sha512":
            return hashlib.sha512(content).hexdigest()
        else:
            raise ValueError(f"Unsupported algorithm: {self.algorithm}")

    def compute_hash_from_file(self, file_path: str) -> str:
        """
        Compute hash of file content (chunked).
        """
        hash_obj = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(self._chunk_size), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()

    def compute_hash_from_stream(self, stream: BinaryIO) -> str:
        """
        Compute hash from binary stream.
        """
        hash_obj = hashlib.sha256()
        while True:
            chunk = stream.read(self._chunk_size)
            if not chunk:
                break
            hash_obj.update(chunk)
        return hash_obj.hexdigest()

    def verify_hash(self, content: bytes, expected_hash: str) -> bool:
        """
        Verify that content matches expected hash.
        """
        computed = self.compute_hash(content)
        return computed == expected_hash

    def verify_hash_from_file(self, file_path: str, expected_hash: str) -> bool:
        """
        Verify file matches expected hash.
        """
        computed = self.compute_hash_from_file(file_path)
        return computed == expected_hash


__all__ = ["FileIntegrityHasher"]
