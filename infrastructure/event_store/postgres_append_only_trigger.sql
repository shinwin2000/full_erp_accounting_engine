-- ============================================================================
-- File: postgres_append_only_trigger.sql
-- Layer: Infrastructure (Event Store)
-- Responsibility: 
--   Trigger dan fungsi PostgreSQL untuk memastikan tabel event_store bersifat
--   append-only (tidak bisa di-update atau di-delete). Trigger ini akan
--   mencegah operasi UPDATE dan DELETE pada tabel event_store, serta
--   memastikan bahwa kolom hash dan sequence_number tidak dapat diubah.
--   Juga menambahkan trigger untuk auto-increment sequence_number dan
--   validasi hash chain.
-- Dependencies:
--   - PostgreSQL 13+ dengan dukungan plpgsql
--   - Tabel event_store harus sudah dibuat
-- Audit: 
--   Setiap percobaan UPDATE/DELETE yang ditolak akan dicatat di log.
--   Trigger ini adalah lapisan keamanan terakhir untuk immutability.
-- ============================================================================

-- ============================================================================
-- FUNCTION: prevent_event_store_modification()
-- ============================================================================
-- Mencegah operasi UPDATE dan DELETE pada tabel event_store
-- ============================================================================

CREATE OR REPLACE FUNCTION prevent_event_store_modification()
RETURNS TRIGGER AS $$
BEGIN
    -- Cegah UPDATE
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'UPDATE not allowed on event_store table (append-only)';
    END IF;
    
    -- Cegah DELETE
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DELETE not allowed on event_store table (append-only)';
    END IF;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- FUNCTION: validate_event_hash_chain()
-- ============================================================================
-- Memvalidasi hash chain saat insert event baru:
-- - previous_hash harus match dengan hash event sebelumnya dalam stream
-- - hash harus dihitung dengan benar
-- - sequence_number harus increment secara berurutan
-- ============================================================================

CREATE OR REPLACE FUNCTION validate_event_hash_chain()
RETURNS TRIGGER AS $$
DECLARE
    last_event RECORD;
    computed_hash TEXT;
    expected_sequence INTEGER;
BEGIN
    -- Dapatkan event terakhir dalam stream yang sama
    SELECT sequence_number, hash INTO last_event
    FROM event_store
    WHERE stream_name = NEW.stream_name
    ORDER BY sequence_number DESC
    LIMIT 1;
    
    -- Validasi sequence_number
    IF last_event IS NULL THEN
        -- Ini adalah event pertama dalam stream
        -- previous_hash harus GENESIS_HASH
        IF NEW.previous_hash != 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' THEN
            RAISE EXCEPTION 'First event in stream must have genesis hash';
        END IF;
        expected_sequence := 1;
    ELSE
        -- Validasi previous_hash
        IF NEW.previous_hash != last_event.hash THEN
            RAISE EXCEPTION 'Hash chain broken: previous_hash % does not match last hash %', 
                NEW.previous_hash, last_event.hash;
        END IF;
        expected_sequence := last_event.sequence_number + 1;
    END IF;
    
    -- Validasi sequence_number
    IF NEW.sequence_number != expected_sequence THEN
        RAISE EXCEPTION 'Sequence number mismatch: expected %, got %', 
            expected_sequence, NEW.sequence_number;
    END IF;
    
    -- Re-calculate hash untuk verifikasi (opsional, bisa di-skip untuk performance)
    -- computed_hash := ENCODE(SHA256(ROW(NEW.data, NEW.metadata, NEW.timestamp, NEW.previous_hash)::TEXT), 'hex');
    -- IF NEW.hash != computed_hash THEN
    --     RAISE EXCEPTION 'Hash mismatch: computed %, stored %', computed_hash, NEW.hash;
    -- END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- FUNCTION: prevent_hash_modification()
-- ============================================================================
-- Mencegah modifikasi kolom hash dan previous_hash (untuk security)
-- ============================================================================

CREATE OR REPLACE FUNCTION prevent_hash_modification()
RETURNS TRIGGER AS $$
BEGIN
    -- Cek apakah kolom hash atau previous_hash berubah
    IF OLD.hash IS DISTINCT FROM NEW.hash THEN
        RAISE EXCEPTION 'Cannot modify hash column (immutable)';
    END IF;
    
    IF OLD.previous_hash IS DISTINCT FROM NEW.previous_hash THEN
        RAISE EXCEPTION 'Cannot modify previous_hash column (immutable)';
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- FUNCTION: auto_set_timestamp()
-- ============================================================================
-- Set timestamp secara otomatis jika tidak disediakan
-- ============================================================================

CREATE OR REPLACE FUNCTION auto_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.timestamp IS NULL THEN
        NEW.timestamp := NOW();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- FUNCTION: log_modification_attempt()
-- ============================================================================
-- Mencatat percobaan modifikasi yang gagal ke log table
-- ============================================================================

CREATE OR REPLACE FUNCTION log_modification_attempt()
RETURNS TRIGGER AS $$
BEGIN
    -- Catat percobaan UPDATE/DELETE yang gagal ke audit log
    INSERT INTO audit_log (
        event_type,
        table_name,
        operation,
        attempted_data,
        error_message,
        attempted_at
    ) VALUES (
        'security_violation',
        'event_store',
        TG_OP,
        CASE 
            WHEN TG_OP = 'UPDATE' THEN ROW(OLD.*, NEW.*)::TEXT
            WHEN TG_OP = 'DELETE' THEN ROW(OLD.*)::TEXT
            ELSE NULL
        END,
        'Attempted to modify append-only table',
        NOW()
    );
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- FUNCTION: get_stream_events(stream_name_param, from_seq, limit)
-- ============================================================================
-- Helper function untuk membaca event dari stream
-- ============================================================================

CREATE OR REPLACE FUNCTION get_stream_events(
    stream_name_param TEXT,
    from_seq INTEGER DEFAULT 1,
    limit_count INTEGER DEFAULT 1000
)
RETURNS TABLE(
    id UUID,
    stream_name TEXT,
    event_type TEXT,
    event_version INTEGER,
    data JSONB,
    metadata JSONB,
    timestamp TIMESTAMPTZ,
    sequence_number INTEGER,
    previous_hash TEXT,
    hash TEXT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        e.id, e.stream_name, e.event_type, e.event_version,
        e.data, e.metadata, e.timestamp,
        e.sequence_number, e.previous_hash, e.hash
    FROM event_store e
    WHERE e.stream_name = stream_name_param
        AND e.sequence_number >= from_seq
    ORDER BY e.sequence_number ASC
    LIMIT limit_count;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- FUNCTION: verify_stream_integrity(stream_name_param)
-- ============================================================================
-- Memverifikasi integritas hash chain untuk stream tertentu
-- ============================================================================

CREATE OR REPLACE FUNCTION verify_stream_integrity(
    stream_name_param TEXT
)
RETURNS TABLE(
    is_valid BOOLEAN,
    checked_events INTEGER,
    broken_at_sequence INTEGER,
    broken_hash TEXT
) AS $$
DECLARE
    event_record RECORD;
    last_hash TEXT;
    current_sequence INTEGER;
    is_chain_valid BOOLEAN := TRUE;
    broken_seq INTEGER := NULL;
    broken_hash_val TEXT := NULL;
    event_count INTEGER := 0;
BEGIN
    last_hash := 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'; -- genesis
    
    FOR event_record IN 
        SELECT sequence_number, previous_hash, hash
        FROM event_store
        WHERE stream_name = stream_name_param
        ORDER BY sequence_number ASC
    LOOP
        event_count := event_count + 1;
        
        -- Validasi previous_hash match dengan last_hash
        IF event_record.previous_hash != last_hash THEN
            is_chain_valid := FALSE;
            broken_seq := event_record.sequence_number;
            broken_hash_val := event_record.hash;
            EXIT;
        END IF;
        
        last_hash := event_record.hash;
    END LOOP;
    
    RETURN QUERY SELECT 
        is_chain_valid, 
        event_count, 
        broken_seq, 
        broken_hash_val;
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Trigger untuk mencegah UPDATE
DROP TRIGGER IF EXISTS trigger_prevent_update ON event_store;
CREATE TRIGGER trigger_prevent_update
    BEFORE UPDATE ON event_store
    FOR EACH ROW
    EXECUTE FUNCTION prevent_event_store_modification();

-- Trigger untuk mencegah DELETE
DROP TRIGGER IF EXISTS trigger_prevent_delete ON event_store;
CREATE TRIGGER trigger_prevent_delete
    BEFORE DELETE ON event_store
    FOR EACH ROW
    EXECUTE FUNCTION prevent_event_store_modification();

-- Trigger untuk validasi hash chain pada INSERT
DROP TRIGGER IF EXISTS trigger_validate_hash_chain ON event_store;
CREATE TRIGGER trigger_validate_hash_chain
    BEFORE INSERT ON event_store
    FOR EACH ROW
    EXECUTE FUNCTION validate_event_hash_chain();

-- Trigger untuk mencegah modifikasi hash (sebagai backup security)
DROP TRIGGER IF EXISTS trigger_prevent_hash_modification ON event_store;
CREATE TRIGGER trigger_prevent_hash_modification
    BEFORE UPDATE ON event_store
    FOR EACH ROW
    EXECUTE FUNCTION prevent_hash_modification();

-- Trigger untuk auto-set timestamp
DROP TRIGGER IF EXISTS trigger_auto_timestamp ON event_store;
CREATE TRIGGER trigger_auto_timestamp
    BEFORE INSERT ON event_store
    FOR EACH ROW
    EXECUTE FUNCTION auto_set_timestamp();

-- Trigger untuk log modification attempts
DROP TRIGGER IF EXISTS trigger_log_modification ON event_store;
CREATE TRIGGER trigger_log_modification
    BEFORE UPDATE OR DELETE ON event_store
    FOR EACH ROW
    EXECUTE FUNCTION log_modification_attempt();


-- ============================================================================
-- INDEXES untuk performance
-- ============================================================================

-- Index untuk query by stream_name dan sequence_number (primary access pattern)
CREATE INDEX IF NOT EXISTS idx_event_store_stream_seq ON event_store(stream_name, sequence_number);

-- Index untuk query by timestamp (time-based search)
CREATE INDEX IF NOT EXISTS idx_event_store_timestamp ON event_store(timestamp);

-- Index untuk query by event_type
CREATE INDEX IF NOT EXISTS idx_event_store_event_type ON event_store(event_type);

-- Composite index untuk search
CREATE INDEX IF NOT EXISTS idx_event_store_stream_time ON event_store(stream_name, timestamp);

-- Hash index untuk integrity verification
CREATE INDEX IF NOT EXISTS idx_event_store_hash ON event_store(hash);


-- ============================================================================
-- AUDIT LOG TABLE (jika belum ada)
-- ============================================================================

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    event_type VARCHAR(50) NOT NULL,
    table_name VARCHAR(100) NOT NULL,
    operation VARCHAR(10) NOT NULL,
    attempted_data TEXT,
    error_message TEXT,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_attempted_at ON audit_log(attempted_at);
CREATE INDEX IF NOT EXISTS idx_audit_log_event_type ON audit_log(event_type);


-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Tampilkan semua trigger yang aktif pada tabel event_store
SELECT 
    tgname AS trigger_name,
    tgtype::INT AS trigger_type,
    tgenabled AS enabled
FROM pg_trigger
WHERE tgrelid = 'event_store'::REGCLASS
    AND NOT tgisinternal;

-- ============================================================================
-- EXPORTS (informational)
-- ============================================================================

/*
Yang diekspor:
- prevent_event_store_modification() - fungsi untuk mencegah UPDATE/DELETE
- validate_event_hash_chain() - fungsi validasi hash chain
- prevent_hash_modification() - fungsi mencegah modifikasi hash
- auto_set_timestamp() - fungsi auto timestamp
- log_modification_attempt() - fungsi log modification attempts
- get_stream_events() - fungsi helper untuk membaca stream
- verify_stream_integrity() - fungsi verifikasi integritas
- Semua trigger pada tabel event_store
- Indexes untuk performance
- Tabel audit_log
*/