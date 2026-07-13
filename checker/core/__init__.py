"""
Module: checker/core/__init__.py
Ekspor komponen inti checker.
"""

try:
    from .rca import rca
except ImportError:
    # Fallback: definisikan rca sebagai fungsi dummy jika modul tidak ada
    def rca(*args, **kwargs):
        """Dummy RCA function."""
        return None
