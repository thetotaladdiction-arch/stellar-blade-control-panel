"""UNRUN source controls: public deterministic test keys, no real key or network."""
from pathlib import Path
import sys
sys.path[:0] = [str(Path(__file__).parent), str(Path(__file__).parent / 'source')]
import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from securesystemslib.signer import CryptoSigner
from securesystemslib.exceptions import UnverifiedSignatureError
from tuf.api.metadata import Root, Targets, Snapshot, Timestamp, MetaFile, TargetFile
import policy_engine as engine

NOW = datetime(2030, 1, 2, 12, tzinfo=timezone.utc)
PARENT = '1' * 40


def fixture(timestamp_hours=2, child_hours=48, root_hours=2160, catalog_hours=24):
    # Public deterministic test seeds; never production keys.
    keys = [CryptoSigner(Ed25519PrivateKey.from_private_bytes(bytes([i]) * 32)) for i in range(1, 7)]
    root = Root(version=1, expires=NOW + timedelta(hours=root_hours), consistent_snapshot=True)
    root.roles['root'].threshold = 2
    for key in keys[:3]:
        root.add_key(key.public_key, 'root')
    for role, key in zip(('targets', 'snapshot', 'timestamp'), keys[3:]):
        root.add_key(key.public_key, role)
    def signed(payload, role, signers):
        return engine.staging._signed(payload, role, {role: tuple(signers)}, root)
    raw_root = signed(root, 'root', keys[:2])
    raw_catalog = json.dumps({'schema_version': 1, 'revision': 1,
        'issued_at': (NOW - timedelta(hours=1)).isoformat().replace('+00:00', 'Z'),
        'expires_at': (NOW + timedelta(hours=catalog_hours)).isoformat().replace('+00:00', 'Z'),
        'games': []}, separators=(',', ':')).encode()
    targets = Targets(version=1, expires=NOW + timedelta(hours=child_hours), targets={
        'catalog-stable.json': TargetFile.from_data('catalog-stable.json', raw_catalog)})
    raw_targets = signed(targets, 'targets', [keys[3]])
    def meta(raw):
        return MetaFile(version=1, length=len(raw), hashes={'sha256': hashlib.sha256(raw).hexdigest()})
    raw_snapshot = signed(Snapshot(version=1, expires=NOW + timedelta(hours=child_hours),
        meta={'targets.json': meta(raw_targets)}), 'snapshot', [keys[4]])
    raw_timestamp = signed(Timestamp(version=1, expires=NOW + timedelta(hours=timestamp_hours),
        snapshot_meta=meta(raw_snapshot)), 'timestamp', [keys[5]])
    metadata = dict(zip(('root.json', 'targets.json', 'snapshot.json', 'timestamp.json'),
                        (raw_root, raw_targets, raw_snapshot, raw_timestamp)))
    root_hash = hashlib.sha256(raw_root).hexdigest()
    assembled = engine.repository.assemble(previous_tree={}, metadata=metadata,
        target_data={'catalog-stable.json': raw_catalog}, expected_parent=PARENT,
        trusted_root_sha256=root_hash, now=NOW)
    files = dict(assembled.files)
    policy = {'repository': 'test/repo', 'default_branch': 'trusted',
        'trusted_root_sha256': root_hash, 'timestamp_key_id': keys[5].public_key.keyid,
        'inner_public_keys_hex': {}, 'fixed_role_versions': {'root': 1, 'targets': 1, 'snapshot': 1},
        'minimum_timestamp_version': 1, 'minimum_ledger_sequence': 1,
        'expected_files': sorted(files), 'unchanged_files': [
            {'path': p, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
            for p, raw in files.items() if p not in ('metadata/timestamp.json', 'public-ledger.json')],
        'due_seconds': 10800, 'lifetime_seconds': 21600}
    return files, policy, keys


class Controls(unittest.TestCase):
    def test_real_signed_timestamp_only_and_exact_ledger_increment(self):
        files, policy, keys = fixture()
        result, after = engine.candidate(files, PARENT, policy, keys[5], NOW)
        self.assertEqual(after['timestamp_version'], 2)
        self.assertEqual(after['ledger_sequence'], 2)
        self.assertEqual({p for p in files if files[p] != result[p]},
                         {'metadata/timestamp.json', 'public-ledger.json'})
        engine.repository.verify_tree(files=result, expected_parent=PARENT,
            trusted_root_sha256=policy['trusted_root_sha256'], now=NOW)

    def test_wait_cannot_sign(self):
        files, policy, keys = fixture(timestamp_hours=5)
        with self.assertRaises(engine.Refused):
            engine.candidate(files, PARENT, policy, keys[5], NOW)

    def test_snapshot_key_cannot_renew_timestamp(self):
        files, policy, keys = fixture()
        with self.assertRaises(ValueError):
            engine.candidate(files, PARENT, policy, keys[4], NOW)

    def test_tampered_timestamp_signature_refuses(self):
        files, policy, keys = fixture()
        raw = json.loads(files['metadata/timestamp.json'])
        raw['signed']['version'] += 1
        files['metadata/timestamp.json'] = json.dumps(raw).encode()
        with self.assertRaises(UnverifiedSignatureError):
            engine.candidate(files, PARENT, policy, keys[5], NOW)

    def test_child_deadline_cannot_be_extended_by_timestamp(self):
        files, policy, keys = fixture(child_hours=5)
        self.assertEqual(engine.inspect(files, PARENT, policy, NOW)[3]['decision'],
                         'GENUINE_STAGE_SUCCESSOR_REQUIRED')
        with self.assertRaises(engine.Refused):
            engine.candidate(files, PARENT, policy, keys[5], NOW)

    def test_offline_root_deadline_has_separate_stop(self):
        files, policy, keys = fixture(child_hours=5, root_hours=5)
        self.assertEqual(engine.inspect(files, PARENT, policy, NOW)[3]['decision'], 'ROOT_SUCCESSOR_REQUIRED')

    def test_catalog_deadline_stops_while_roles_still_valid(self):
        files, policy, keys = fixture(catalog_hours=5)
        self.assertEqual(engine.inspect(files, PARENT, policy, NOW)[3]['decision'],
                         'GENUINE_STAGE_SUCCESSOR_REQUIRED')

    def test_wrong_public_root_and_missing_history_refuse(self):
        files, policy, keys = fixture()
        policy['trusted_root_sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            engine.inspect(files, PARENT, policy, NOW)
        files.pop('metadata/1.root.json')
        with self.assertRaises(engine.Refused):
            engine.inspect(files, PARENT, policy, NOW)

    def test_fork_pr_branch_unreviewed_source_and_replay_refuse(self):
        _, policy, _ = fixture()
        env = {'GITHUB_EVENT_NAME': 'schedule', 'GITHUB_REPOSITORY': 'test/repo',
               'GITHUB_REF': 'refs/heads/trusted', 'CHECKED_OUT_PUBLISHER_SHA': 'a' * 40,
               'PUBLISHER_REVIEWED_SOURCE_SHA': 'a' * 40, 'GITHUB_RUN_ATTEMPT': '1',
               'GITHUB_WORKFLOW_REF': 'test/repo/.github/workflows/aeroneus-timestamp.yml@refs/heads/trusted'}
        event = {'repository': {'full_name': 'test/repo', 'default_branch': 'trusted', 'fork': False}}
        engine.context(env, event, policy)
        for field, value in [('GITHUB_EVENT_NAME', 'pull_request'), ('GITHUB_REF', 'refs/heads/other'),
                             ('CHECKED_OUT_PUBLISHER_SHA', 'b' * 40), ('GITHUB_RUN_ATTEMPT', '2')]:
            with self.subTest(field=field), self.assertRaises(engine.Refused):
                engine.context(dict(env, **{field: value}), event, policy)
        event['repository']['fork'] = True
        with self.assertRaises(engine.Refused):
            engine.context(env, event, policy)

    def test_parent_race_refuses_without_rebase(self):
        with self.assertRaises(engine.Refused):
            engine.expected_parent('2' * 40, PARENT)

    def test_no_extra_file_or_changed_child_bytes_accepted(self):
        files, policy, _ = fixture()
        files['unexpected.py'] = b'not executable'
        with self.assertRaises(engine.Refused):
            engine.inspect(files, PARENT, policy, NOW)
        del files['unexpected.py']
        files['metadata/1.snapshot.json'] += b' '
        with self.assertRaises(engine.Refused):
            engine.inspect(files, PARENT, policy, NOW)

    def test_due_boundary_and_actual_clock(self):
        files, policy, keys = fixture(timestamp_hours=3)
        self.assertEqual(engine.inspect(files, PARENT, policy, NOW)[3]['decision'], 'RENEW_DUE')
        self.assertEqual(engine.inspect(files, PARENT, policy, NOW - timedelta(seconds=1))[3]['decision'], 'WAIT')
        _, after = engine.candidate(files, PARENT, policy, keys[5], NOW + timedelta(seconds=1))
        self.assertEqual(after['expires'], (NOW + timedelta(hours=6, seconds=1)).isoformat())


if __name__ == '__main__':
    unittest.main(verbosity=2)
