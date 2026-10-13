"""Source-order offline windows preserve prior runs and native occurrence identity."""
from pathlib import Path
from dataclasses import replace
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

import _paths  # noqa: F401
from formowl_ingestion.extractors.mail.pst import _readpst_sidecar_parent_window
from scripts import issue56_attachment_backfill as backfill
from test_issue56_attachment_backfill import AttachmentBackfillTests
import test_issue56_attachment_backfill as fixture_tools


class AttachmentBackfillWindowTests(unittest.TestCase):
    def fixture(self):
        result = AttachmentBackfillTests()._fixture()
        self.addCleanup(shutil.rmtree, result[0])
        return result

    def test_window_keeps_source_order_and_global_ordinals(self):
        root = Path('/fixture')
        parents = {
            root/'3': [root/'3-note.txt'],
            root/'1': [root/'1-table.xlsx', root/'1-note.docx'],
            root/'2': [root/'2-report.pdf'],
        }
        rows, scope, ordinal = _readpst_sidecar_parent_window(
            parents, export_root=root,
            config={'attachment_sidecar_parent_start': 1, 'attachment_sidecar_parent_count': 1},
        )
        self.assertEqual([p.name for p, _ in rows], ['2'])
        self.assertEqual(ordinal, 2)
        self.assertEqual(scope, {'parent_start': 1, 'parent_count': 1,
                                'requested_parent_count': 1, 'total_parent_count': 3,
                                'sidecar_ordinal_offset': 2})
        tail, tail_scope, tail_ordinal = _readpst_sidecar_parent_window(
            parents, export_root=root,
            config={'attachment_sidecar_parent_start': 2, 'attachment_sidecar_parent_count': 10},
        )
        self.assertEqual([p.name for p, _ in tail], ['3'])
        self.assertEqual(tail_scope['parent_count'], 1)
        self.assertEqual(tail_ordinal, 3)
        all_rows, all_scope, all_ordinal = _readpst_sidecar_parent_window(
            parents, export_root=root, config={},
        )
        self.assertEqual([p.name for p, _ in all_rows], ['1', '2', '3'])
        self.assertIsNone(all_scope)
        self.assertEqual(all_ordinal, 0)

    def test_window_seal_hashes_selected_files_only_and_detects_drift(self):
        root = Path(tempfile.mkdtemp(prefix='sidecar-window-'))
        self.addCleanup(shutil.rmtree, root)
        for name in ('1', '1-a.txt', '2', '2-b.xlsx'):
            (root/name).write_bytes(name.encode())
        config = {'attachment_sidecar_parent_start': 1, 'attachment_sidecar_parent_count': 1}
        with patch.object(backfill, '_hash_file', wraps=backfill._hash_file) as reader:
            first = backfill._export_seal(root, config=config)
        self.assertEqual({call.args[0].name for call in reader.call_args_list}, {'2', '2-b.xlsx'})
        self.assertEqual(first['file_count'], 2)
        self.assertEqual(first['sidecar_count'], 1)
        (root/'1-a.txt').write_bytes(b'not in this declared window')
        self.assertEqual(backfill._export_seal(root, config=config), first)
        (root/'2-b.xlsx').write_bytes(b'changed selected source')
        self.assertNotEqual(backfill._export_seal(root, config=config), first)

    def test_invalid_windows_fail_before_job_or_ledger_write(self):
        root, stores, _, _, manifest, export = self.fixture()
        before = [job.to_dict() for job in stores[1].list()]
        for start, count in ((True, 1), (-1, 1), (0, 0), (0, True), (0, None), (None, 1), (1, 1)):
            with self.subTest(start=start, count=count):
                ledger = root/'invalid-ledger.json'
                with self.assertRaisesRegex(backfill.BackfillError, 'sidecar_parent_window_invalid'):
                    backfill.run_attachment_backfill(
                        store_directory=root, parent_binding_manifest_path=manifest,
                        ledger_path=ledger, existing_export_root=export,
                        config={'attachment_sidecar_parent_start': start,
                                'attachment_sidecar_parent_count': count},
                    )
                self.assertFalse(ledger.exists())
                self.assertEqual([job.to_dict() for job in stores[1].list()], before)

    def test_preceding_sidecar_membership_drift_rejects_completed_ledger_reuse(self):
        original_runner = fixture_tools._Runner.__call__
        second_message = fixture_tools._mail_bytes().replace(
            b'backfill-parent@example.test', b'window-second@example.test',
        )

        def two_messages(runner, command, timeout):
            result = original_runner(runner, command, timeout)
            directory = Path(command[command.index('-o') + 1])
            (directory/'2.eml').write_bytes(second_message)
            return result

        with patch.object(fixture_tools._Runner, '__call__', two_messages):
            root, stores, asset, prior, manifest, export = self.fixture()
        parents = [stores[3].get(key) for key in prior.observation_ids]
        parents = [item for item in parents if item.observation_type == 'email_message']
        self.assertEqual(len(parents), 2)
        records = []
        for parent in parents:
            fixture_tools._write_manifest(
                manifest, asset=asset, prior_job=prior,
                prior_run=stores[2].get(prior.extractor_run_ids[0]), parent=parent,
            )
            binding = json.loads(manifest.read_text())
            records.extend(binding['records'])
        binding.pop('artifact_fingerprint')
        binding.update(records=records, parent_binding_count=2,
                       parent_binding_fingerprint=fixture_tools.sha256_json(records))
        binding['artifact_fingerprint'] = fixture_tools.sha256_json(binding)
        manifest.write_text(json.dumps(binding))
        (export/'2').write_bytes(second_message)
        (export/'2-table.xlsx').write_bytes(fixture_tools._xlsx_bytes())
        config = {'attachment_sidecar_parent_start': 1, 'attachment_sidecar_parent_count': 1}
        args = dict(store_directory=root, parent_binding_manifest_path=manifest,
                    existing_export_root=export, config=config,
                    ledger_path=root/'nonzero-window.json', batch_id='nonzero-window')
        result = backfill.run_attachment_backfill(**args)
        self.assertEqual(result['status_counts'], {'succeeded': 1})
        sealed = backfill._export_seal(export, config=config)
        self.assertEqual(sealed['parent_window']['sidecar_ordinal_offset'], 3)
        before = {p: p.read_bytes() for p in (root/'ingestion').rglob('*.json')}
        ledger = (root/'nonzero-window.json').read_bytes()
        (export/'1-added.txt').write_bytes(b'new preceding native sidecar')
        changed = backfill._export_seal(export, config=config)
        self.assertEqual(changed['file_stream_fingerprint'], sealed['file_stream_fingerprint'])
        self.assertEqual(changed['parent_window']['sidecar_ordinal_offset'], 4)
        self.assertNotEqual(changed, sealed)
        with self.assertRaisesRegex(backfill.BackfillError, 'batch_ledger_binding_invalid'):
            backfill.run_attachment_backfill(**args)
        self.assertEqual((root/'nonzero-window.json').read_bytes(), ledger)
        self.assertEqual({p: p.read_bytes() for p in (root/'ingestion').rglob('*.json')}, before)
        (export/'1-added.txt').unlink()
        self.assertEqual(backfill.run_attachment_backfill(**args), result)

    def test_window_new_run_preserves_previous_assets_and_reuses_completed_window(self):
        root, stores, _, _, manifest, export = self.fixture()
        args = dict(store_directory=root, parent_binding_manifest_path=manifest,
                    existing_export_root=export)
        full = backfill.run_attachment_backfill(**args, ledger_path=root/'full.json', batch_id='before')
        self.assertEqual(full['status_counts'], {'succeeded': 1})
        old_assets = {a.asset_id: a.to_dict() for a in stores[0].list()}
        old_jobs = {j.ingestion_job_id: j.to_dict() for j in stores[1].list()}
        window_args = dict(
            **args, ledger_path=root/'window.json', batch_id='window-new',
            config={'attachment_sidecar_parent_start': 0, 'attachment_sidecar_parent_count': 1},
        )
        result = backfill.run_attachment_backfill(**window_args)
        self.assertEqual(result['status_counts'], {'succeeded': 1})
        self.assertFalse(result['source_completeness_certified'])
        self.assertFalse(result['rag_activation_performed'])
        for key, expected in old_assets.items():
            self.assertEqual(stores[0].get(key).to_dict(), expected)
        for key, expected in old_jobs.items():
            self.assertEqual(stores[1].get(key).to_dict(), expected)
        ledger_bytes = (root/'window.json').read_bytes()
        ledger = json.loads(ledger_bytes)
        self.assertEqual(ledger['binding']['export_seal']['parent_window']['parent_count'], 1)
        new_jobs = [j for j in stores[1].list() if j.ingestion_job_id not in old_jobs]
        self.assertEqual(len(new_jobs), 1)
        evidence = [stores[3].get(i) for i in new_jobs[0].observation_ids]
        self.assertTrue(any(o.observation_type == 'table_cell' for o in evidence))
        self.assertTrue(any(o.observation_type == 'paragraph' for o in evidence))
        with patch.object(backfill.ReadpstSidecarBackfillExtractor, 'extract',
                          side_effect=AssertionError('completed window reparsed')):
            self.assertEqual(backfill.run_attachment_backfill(**window_args), result)
        self.assertEqual((root/'window.json').read_bytes(), ledger_bytes)

    def test_interrupted_window_requires_new_batch_without_overwriting_children(self):
        root, stores, _, prior, manifest, export = self.fixture()
        args = dict(store_directory=root, parent_binding_manifest_path=manifest,
                    existing_export_root=export,
                    config={'attachment_sidecar_parent_start': 0,
                            'attachment_sidecar_parent_count': 1})
        backfill.run_attachment_backfill(**args, ledger_path=root/'old.json', batch_id='old')
        old = next(j for j in stores[1].list() if j.ingestion_job_id != prior.ingestion_job_id)
        # Model the power-loss boundary: child records exist, parent has not
        # published run/Observation membership. Never reset real jobs this way.
        interrupted = replace(old, status='running', completed_at=None,
                              observation_ids=[], extractor_run_ids=[])
        stores[1].create(interrupted)
        before_assets = {a.asset_id: a.to_dict() for a in stores[0].list()}
        before_runs = {r.extractor_run_id: r.to_dict() for r in stores[2].list()}
        old_ledger = (root/'old.json').read_bytes()
        with self.assertRaisesRegex(backfill.BackfillError, 'interrupted_job_requires_new_batch'):
            backfill.run_attachment_backfill(**args, ledger_path=root/'old.json', batch_id='old')
        recovered = backfill.run_attachment_backfill(
            **args, ledger_path=root/'new.json', batch_id='new',
        )
        self.assertEqual(recovered['status_counts'], {'succeeded': 1})
        self.assertFalse(recovered['source_completeness_certified'])
        self.assertEqual((root/'old.json').read_bytes(), old_ledger)
        self.assertEqual(stores[1].get(old.ingestion_job_id).to_dict(), interrupted.to_dict())
        for key, expected in before_assets.items():
            self.assertEqual(stores[0].get(key).to_dict(), expected)
        for key, expected in before_runs.items():
            self.assertEqual(stores[2].get(key).to_dict(), expected)


if __name__ == '__main__':
    unittest.main()
