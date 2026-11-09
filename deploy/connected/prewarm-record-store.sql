-- Run after a record rebuild commits and after each web deployment, before
-- checking the read-only application query plans. Use the packaged SQL file.
-- docker exec -i formowl-records-pg psql -X -U formowl -d formowl < deploy/connected/prewarm-record-store.sql
-- The existing pg_prewarm extension is installed in public. The first pass reads
-- the main forks into the OS cache. The second loads indexes into shared buffers.
\set ON_ERROR_STOP on
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO $warm$
DECLARE
    mode text;
    relation record;
    blocks bigint;
    read_blocks bigint;
    tables integer;
    indexes integer;
    block_bytes bigint := current_setting('block_size')::bigint;
BEGIN
    FOREACH mode IN ARRAY ARRAY['read', 'buffer'] LOOP
        read_blocks := 0;
        tables := 0;
        indexes := 0;
        FOR relation IN
            WITH record_tables(id) AS (
                SELECT unnest(ARRAY['public.header_signature'::regclass, 'public.record'::regclass,
                    'public.record_value'::regclass, 'public.entity'::regclass, 'public.record_entity'::regclass,
                    'public.record_unresolved_value_summary'::regclass,
                    'public.record_unresolved_value_summary_coverage'::regclass])
            ), heaps(id) AS (
                SELECT id FROM record_tables
                UNION ALL
                SELECT c.reltoastrelid FROM pg_class c JOIN record_tables t ON t.id=c.oid
                WHERE c.reltoastrelid <> 0
            ), relations(id, is_index) AS (
                SELECT id, false FROM heaps
                UNION ALL
                SELECT i.indexrelid, true FROM pg_index i JOIN heaps h ON h.id=i.indrelid
            )
            SELECT id, is_index FROM relations WHERE mode='read' OR is_index ORDER BY is_index, id
        LOOP
            blocks := public.pg_prewarm(relation.id::regclass, mode);
            IF blocks IS DISTINCT FROM pg_relation_size(relation.id::regclass) / block_bytes THEN
                RAISE EXCEPTION 'Incomplete record-store warmup for % in % mode', relation.id, mode;
            END IF;
            read_blocks := read_blocks + blocks;
            IF relation.is_index THEN indexes := indexes + 1; ELSE tables := tables + 1; END IF;
        END LOOP;
        RAISE NOTICE 'record_cache %', json_build_object('mode',mode,'heaps',tables,'indexes',indexes,
            'blocks',read_blocks,'block_bytes',block_bytes,'read_only',current_setting('transaction_read_only'));
    END LOOP;
END
$warm$;
COMMIT;
