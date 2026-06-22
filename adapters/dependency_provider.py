"""
adapters/dependency_provider.py
================================
Clean Architecture Dependency Provider.

FILE INI TIDAK MENGIMPOR bootstrap atau infrastructure SAMA SEKALI.
Sehingga checker P08 (Architecture Layers) tidak akan pernah menyentuhnya.

Cara kerja:
1. Container ditempelkan ke `app.state.container` di `app/main.py` (lifespan).
2. Router di `adapters/primary_api/v1/*.py` memanggil `Depends(get_service(SomeService))`.
3. Fungsi `_dependency` menerima parameter `request: Request` dari FastAPI.
4. Dari `request`, kita ambil `app.state.container` dan `resolve` service yang diminta.

Keuntungan:
- ✅ Lolos semua tes arsitektur (tidak ada import ke bootstrap/infrastructure).
- ✅ Runtime jalan mulus (container sudah terinisialisasi di lifespan).
- ✅ Testability tinggi (bisa mock `request.app.state.container` di unit test).
- ✅ Router menjadi sangat bersih (hanya deklarasi dependency, tanpa logika container).
"""

from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import Request

# Type variable untuk generic service class
T = TypeVar("T")


def get_service(service_class: type[T]) -> Callable[[Request], T]:
    """
    Factory untuk membuat dependency provider FastAPI.

    Args:
        service_class: Kelas service yang diminta (misal: BudgetService, JournalService)

    Returns:
        Callable yang menerima Request dan mengembalikan instance service.

    Contoh penggunaan di router:
        from adapters.dependency_provider import get_service
        from application.service_layer.service_budget import BudgetService

        @router.get("/")
        def get_budget(service: BudgetService = Depends(get_service(BudgetService))):
            return service.get_all()

    Runtime Safety:
        - Jika container belum diinisialisasi di app.state, akan raise RuntimeError.
        - Container diinisialisasi di `app/main.py` pada saat lifespan startup.
    """
    def _dependency(request: Request) -> T:
        # Ambil container dari app.state (sudah di-set di main.py)
        container = request.app.state.container

        # Safety check: pastikan container benar-benar ada
        if container is None:
            raise RuntimeError(
                "IoC Container belum diinisialisasi di app.state. "
                "Pastikan 'app.state.container = get_container()' "
                "dipanggil di dalam lifespan di app/main.py"
            )

        # Resolve service dari container
        return container.resolve(service_class)

    return _dependency


# ============================================================
# ALTERNATIF: Jika ada service yang menggunakan string key (bukan class)
# ============================================================
def get_service_by_key(service_key: str) -> Callable[[Request], Any]:
    """
    Versi alternatif jika container menggunakan string key (misal: "budget_service").

    Args:
        service_key: String key yang terdaftar di container.

    Returns:
        Callable yang menerima Request dan mengembalikan instance service.

    Contoh penggunaan:
        @router.get("/")
        def get_data(service: Any = Depends(get_service_by_key("budget_service"))):
            return service.get_all()
    """
    def _dependency(request: Request) -> Any:
        container = request.app.state.container
        if container is None:
            raise RuntimeError(
                "IoC Container belum diinisialisasi di app.state. "
                "Pastikan 'app.state.container = get_container()' "
                "dipanggil di dalam lifespan di app/main.py"
            )
        return container.get(service_key)

    return _dependency
