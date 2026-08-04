SELECT
  (SELECT count(*) FROM account WHERE legal_entity_id = '11111111-1111-1111-1111-111111111111') AS accounts,
  (SELECT count(*) FROM journal_header WHERE legal_entity_id = '11111111-1111-1111-1111-111111111111') AS journals,
  (SELECT count(*) FROM legal_entity_branch WHERE parent_entity_id = '11111111-1111-1111-1111-111111111111') AS branches,
  (SELECT count(*) FROM iam_user WHERE legal_entity_ids @> '"11111111-1111-1111-1111-111111111111"') AS iam_users;
