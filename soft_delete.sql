UPDATE legal_entity
SET deleted_at = NOW(), is_active = false, status = 'inactive', updated_at = NOW()
WHERE id = '11111111-1111-1111-1111-111111111111';
