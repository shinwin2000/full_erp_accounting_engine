# ==========================================
# STAGE 1: Builder (Instalasi & Kompilasi)
# ==========================================
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    build-essential \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install dependencies ke folder lokal untuk dipindahkan nanti
RUN pip install --no-cache-dir --user -r requirements.txt


# ==========================================
# STAGE 2: Runtime (Image Akhir yang Ringan)
# ==========================================
FROM python:3.11-slim AS runtime

WORKDIR /workspace

# Install libpq saja (karena dibutuhkan psycopg2/asyncpg untuk PostgreSQL di waktu runtime)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Salin python packages hasil kompilasi dari stage builder
COPY --from=builder /root/.local /root/.local
# Salin seluruh kode aplikasi dari mesin lokal
COPY . .

# Pastikan binary dari python packages masuk ke PATH
ENV PATH=/root/.local/bin:$PATH

EXPOSE 8000

# PERBAIKAN UTAMA: Menggunakan "app.main:app" jika main.py berada di dalam folder app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]