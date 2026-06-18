#!/usr/bin/env python3
"""
Integration: Saga State Persistence
Menguji bahwa state saga (orchestrator) dapat disimpan ke database dan
dipulihkan ketika proses restart, sehingga saga dapat melanjutkan kompensasi.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import JSON, Column, DateTime, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# ============================================================================
# 1. Definisi model untuk saga state (tabel database)
# ============================================================================
Base = declarative_base()


class SagaStateModel(Base):
    __tablename__ = "saga_state"

    id = Column(String(36), primary_key=True)
    state_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============================================================================
# 2. Custom JSON encoder untuk Decimal (karena Decimal tidak serializable)
# ============================================================================
class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


# ============================================================================
# 3. Implementasi SagaStateStore (jika belum ada di aplikasi)
# ============================================================================
class SagaStateStore:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def save(self, saga_id: str, state: dict):
        """Simpan state saga ke database."""
        session = self.session_factory()
        state_json = json.dumps(state, cls=CustomJSONEncoder)
        existing = session.query(SagaStateModel).filter_by(id=saga_id).first()
        if existing:
            existing.state_data = state_json
            existing.updated_at = datetime.utcnow()
        else:
            new_state = SagaStateModel(id=saga_id, state_data=state_json)
            session.add(new_state)
        session.commit()
        session.close()

    def load(self, saga_id: str) -> dict | None:
        """Muat state saga dari database."""
        session = self.session_factory()
        record = session.query(SagaStateModel).filter_by(id=saga_id).first()
        session.close()
        if record:
            return json.loads(record.state_data)
        return None


# ============================================================================
# 4. Implementasi dummy ProcurementSaga (jika belum ada)
#    Asumsikan saga memiliki metode start() dan resume()
# ============================================================================
class ProcurementSaga:
    def __init__(self, state_store: SagaStateStore):
        self.state_store = state_store
        self.current_step = None
        self.saga_id = None

    def start(self, saga_id: str, data: dict):
        """Mulai saga baru."""
        self.saga_id = saga_id
        self.current_step = "create_po"
        state = {
            "current_step": self.current_step,
            "compensating": False,
            "data": data,
        }
        self.state_store.save(saga_id, state)

    def resume(self, saga_id: str):
        """Lanjutkan saga yang pernah terhenti (crash/restart)."""
        state = self.state_store.load(saga_id)
        if not state:
            raise ValueError(f"Saga state not found for id {saga_id}")
        self.saga_id = saga_id
        self.current_step = state["current_step"]
        # Di sini bisa ditambahkan logika untuk melanjutkan eksekusi ke step berikutnya
        # sesuai dengan state yang dimuat. Untuk keperluan test, kita cukup set current_step.
        # Contoh: jika state['current_step'] == 'create_po', maka lanjut ke step berikutnya
        # if self.current_step == "create_po":
        #     self.current_step = "create_grn"
        #     ... dst

    def get_current_step(self) -> str:
        return self.current_step


# ============================================================================
# 5. Fixtures untuk test
# ============================================================================
@pytest.fixture
def session_factory():
    """Menyediakan session factory dengan database SQLite in-memory."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)  # Buat tabel
    return sessionmaker(bind=engine)


@pytest.fixture
def state_store(session_factory):
    """Menyediakan instance SagaStateStore dengan session factory."""
    return SagaStateStore(session_factory)


@pytest.fixture
def saga_instance(state_store):
    """Menyediakan instance ProcurementSaga."""
    return ProcurementSaga(state_store)


# ============================================================================
# 6. Test cases
# ============================================================================
def test_save_and_load_saga_state(state_store):
    """Test penyimpanan dan pemuatan state saga."""
    saga_id = "SAGA-PROC-001"
    state = {
        "current_step": "create_po",
        "compensating": False,
        "data": {"po_id": "PO-123", "amount": Decimal("5000000")},
    }
    state_store.save(saga_id, state)

    loaded = state_store.load(saga_id)
    assert loaded["current_step"] == "create_po"
    assert loaded["data"]["po_id"] == "PO-123"
    assert Decimal(loaded["data"]["amount"]) == Decimal("5000000")


def test_saga_resume_after_crash(state_store, saga_instance):
    """Test bahwa saga dapat melanjutkan setelah crash menggunakan state yang tersimpan."""
    saga_id = "SAGA-PROC-002"
    initial_data = {"product": "A", "qty": 10}

    # Mulai saga
    saga_instance.start(saga_id, initial_data)
    assert saga_instance.get_current_step() == "create_po"

    # Simulasi crash: kita hanya punya state tersimpan di database
    state = state_store.load(saga_id)
    assert state is not None
    assert state["current_step"] == "create_po"

    # Restart saga (aplikasi restart, buat instance baru)
    new_saga = ProcurementSaga(state_store)
    new_saga.resume(saga_id)

    # Pastikan state dipulihkan
    assert new_saga.get_current_step() == "create_po"

    # (Opsional) Jika ingin melanjutkan eksekusi, bisa ditambahkan step berikutnya
    # Misalnya dalam implementasi nyata, resume() akan memanggil method untuk melanjutkan
    # ke step selanjutnya. Untuk test ini, kita hanya pastikan state bisa dimuat.
