"""Public fixtures/deterministic dummy keys only; no live network, Git or provider.
Fixed clocks below are test scenarios, never the hosted execution clock.
"""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / 'source')]
import policy_engine as engine
import run_hosted as hosted
from test_online import CryptoSigner, Ed25519PrivateKey, Root, Targets, Snapshot, Timestamp, MetaFile, TargetFile

BASE = datetime(2026, 11, 10, 4, 37, 27, tzinfo=timezone.utc)
SNAPSHOT_END = datetime(2026, 11, 13, 4, 37, 27, tzinfo=timezone.utc)
INNER_END = datetime(2026, 11, 15, 11, 17, 25, tzinfo=timezone.utc)
PARENT = 'e93a049ec8bb5c4f6118f0e173fb4d4fecbb7545'
POLICY = json.loads((HERE / 'policy.json').read_text())
FIXTURE = HERE / 'testdata/published13'
FILES = {p.relative_to(FIXTURE).as_posix(): p.read_bytes() for p in FIXTURE.rglob('*') if p.is_file()}


def fixture13(snapshot_end=SNAPSHOT_END):
    """Actual public inner payloads; ONLY dummy metadata role keys/signatures."""
    keys = [CryptoSigner(Ed25519PrivateKey.from_private_bytes(bytes([i]) * 32)) for i in range(1, 7)]
    root = Root(version=1, expires=BASE+timedelta(days=80), consistent_snapshot=True)
    root.roles['root'].threshold = 2
    for key in keys[:3]:
        root.add_key(key.public_key, 'root')
    for role, key in zip(engine.staging.ROLES, keys[3:]):
        root.add_key(key.public_key, role)
    def sign(payload, role):
        selected = keys[:2] if role == 'root' else [keys[3+engine.staging.ROLES.index(role)]]
        return engine.staging._signed(payload, role, {role: tuple(selected)}, root)
    root_raw = sign(root, 'root')
    root_hash = hashlib.sha256(root_raw).hexdigest()
    _, data, _ = engine.git_operator._extract(FILES)
    def metadata(version, timestamp_version):
        targets = sign(Targets(version=version, expires=BASE+timedelta(days=14),
            targets={name: TargetFile.from_data(name, raw) for name, raw in data.items()}), 'targets')
        snapshot = sign(Snapshot(version=version, expires=snapshot_end,
            meta={'targets.json': MetaFile.from_data(version, targets, ['sha256'])}), 'snapshot')
        timestamp = sign(Timestamp(version=timestamp_version, expires=BASE+timedelta(hours=6),
            snapshot_meta=MetaFile.from_data(version, snapshot, ['sha256'])), 'timestamp')
        return dict(zip(('root.json', 'targets.json', 'snapshot.json', 'timestamp.json'), (root_raw, targets, snapshot, timestamp)))
    first = metadata(1, 1)
    second = metadata(2, 2)
    initial = BASE-timedelta(hours=2)
    files = dict(engine.repository.assemble(previous_tree={}, metadata=second, target_data=data,
        expected_parent=PARENT, trusted_root_sha256=root_hash, now=initial,
        initial_history={'metadata/1.'+r+'.json': first[r+'.json'] for r in ('targets', 'snapshot')}).files)
    for count in (1, 2):
        now = initial+timedelta(minutes=10*count)
        state = engine.repository.verify_tree(files=files, expected_parent=PARENT, trusted_root_sha256=root_hash, now=now)
        renewed = engine.renewal.create(state, signers=(keys[5],), expires=BASE+timedelta(hours=6), now=now)
        current, _, _ = engine.git_operator._extract(files)
        current['timestamp.json'] = renewed.timestamp_bytes
        files = dict(engine.repository.assemble(previous_tree=files, metadata=current, target_data=data,
            expected_parent=PARENT, trusted_root_sha256=root_hash, now=now, ledger_bytes=renewed.ledger_bytes).files)
    files = dict(engine.repository.assemble(previous_tree=files, metadata=metadata(3, 5), target_data=data,
        expected_parent=PARENT, trusted_root_sha256=root_hash, now=BASE).files)
    policy = copy.deepcopy(POLICY)
    policy.update(trusted_root_sha256=root_hash, timestamp_key_id=keys[5].public_key.keyid,
        unchanged_files=[dict(path=p, size=len(b), sha256=hashlib.sha256(b).hexdigest())
                         for p, b in sorted(files.items()) if p not in {'metadata/timestamp.json', 'public-ledger.json'}])
    return files, policy, keys[5]


def event_context(event_name):
    event = dict(repository=dict(full_name=POLICY['repository'], default_branch=POLICY['default_branch'], fork=False))
    env = dict(GITHUB_EVENT_NAME=event_name, GITHUB_REPOSITORY=POLICY['repository'],
        GITHUB_REF='refs/heads/'+POLICY['default_branch'], GITHUB_RUN_ATTEMPT='1',
        GITHUB_WORKFLOW_REF=POLICY['repository']+'/.github/workflows/aeroneus-timestamp.yml@refs/heads/'+POLICY['default_branch'],
        PUBLISHER_REVIEWED_SOURCE_SHA='a'*40, CHECKED_OUT_PUBLISHER_SHA='a'*40, GITHUB_RUN_ID='123')
    return env, event


class Successor(unittest.TestCase):
    def assert_no_sign(self, files, policy, when):
        with patch.object(engine.renewal, 'create') as signing:
            with self.assertRaises(Exception):
                engine.candidate(files, PARENT, policy, object(), when)
            signing.assert_not_called()

    def test_actual_thirteen_policy_and_wait(self):
        plan = engine.inspect(FILES, PARENT, POLICY, BASE+timedelta(hours=1))[3]
        self.assertEqual(len(FILES), 13)
        self.assertEqual((plan['timestamp_version'], plan['ledger_sequence']), (5, 4))
        self.assertEqual(plan['tree'], '457110192d05a8017a6ca8d2f65917446309b9a4')
        self.assertEqual(plan['decision'], 'WAIT')
        self.assertEqual(plan['child_deadline'], SNAPSHOT_END.isoformat())
        self.assertIsNone(POLICY['hosting_consent_record'])

    def test_dummy_six_five_changes_only_timestamp_and_ledger(self):
        files, policy, key = fixture13()
        result, after = engine.candidate(files, PARENT, policy, key, BASE+timedelta(hours=3))
        self.assertEqual(len(result), 13)
        self.assertEqual((after['timestamp_version'], after['ledger_sequence']), (6, 5))
        self.assertEqual({p for p in files if files[p] != result[p]}, {'metadata/timestamp.json', 'public-ledger.json'})

    def test_nov13_snapshot_six_hour_boundary_refuses_before_signing(self):
        when = SNAPSHOT_END-timedelta(hours=6)
        self.assertEqual(engine.inspect(FILES, PARENT, POLICY, when)[3]['decision'], 'GENUINE_STAGE_SUCCESSOR_REQUIRED')
        self.assert_no_sign(FILES, POLICY, when)

    def test_nov13_expired_snapshot_cannot_be_replaced_by_timestamp(self):
        self.assert_no_sign(FILES, POLICY, SNAPSHOT_END)

    def test_nov15_inner_boundary_even_with_later_dummy_snapshot(self):
        files, policy, _ = fixture13(BASE+timedelta(days=6))
        when = INNER_END-timedelta(hours=6)
        plan = engine.inspect(files, PARENT, policy, when)[3]
        self.assertEqual(plan['child_deadline'], INNER_END.isoformat())
        self.assertEqual(plan['decision'], 'GENUINE_STAGE_SUCCESSOR_REQUIRED')
        self.assert_no_sign(files, policy, when)

    def test_nov15_expired_inner_content_cannot_be_replaced_by_timestamp(self):
        files, policy, _ = fixture13(BASE+timedelta(days=6))
        self.assert_no_sign(files, policy, INNER_END)

    def test_manual_context_check_only_and_fork_refused(self):
        env, event = event_context('workflow_dispatch')
        engine.context(env, event, POLICY, mode='check')
        with self.assertRaises(engine.Refused):
            engine.context(env, event, POLICY, mode='publish')
        event['repository']['fork'] = True
        with self.assertRaises(engine.Refused):
            engine.context(env, event, POLICY, mode='check')

    def test_manual_hosted_check_and_publish_pre_sign_refusal(self):
        temp_parent = os.environ.get('AERONEUS_TEST_TMP', os.environ.get('RUNNER_TEMP'))
        self.assertIsNotNone(temp_parent, 'Set isolated test output directory')
        directory = Path(tempfile.mkdtemp(prefix='hosted-controls-', dir=temp_parent))
        env, event = event_context('workflow_dispatch')
        (directory/'event.json').write_text(json.dumps(event))
        env.update(GITHUB_EVENT_PATH=str(directory/'event.json'), RUNNER_TEMP=str(directory), GITHUB_OUTPUT=str(directory/'output'))
        calls = []
        class PublicGitFixture:
            def __init__(self, path): calls.append('public')
            def tip(self, ref): return PARENT
            def snapshot(self, parent, ref, subject, policy): return FILES
        resource = SimpleNamespace(RLIMIT_CORE=0, setrlimit=lambda *args: None)
        with patch.dict(os.environ, env, clear=True), patch.dict(sys.modules, {'resource': resource}), \
             patch.object(sys, 'platform', 'linux'), patch.object(hosted, 'load_engine', return_value=engine), \
             patch.object(hosted, 'Git', PublicGitFixture), patch.object(engine, 'utc', return_value=BASE+timedelta(hours=1)), \
             patch.object(engine, 'signer_from_memory', side_effect=AssertionError('No signer in dry run')) as signer:
            with patch.object(sys, 'argv', ['run_hosted.py', 'check']):
                hosted.main()
            self.assertEqual((directory/'output').read_text(), 'decision=WAIT\n')
            with patch.object(sys, 'argv', ['run_hosted.py', 'publish']), self.assertRaises(engine.Refused):
                hosted.main()
            os.environ['AERONEUS_TIMESTAMP_PEM'] = 'DUMMY_REJECT_BEFORE_GIT'
            with patch.object(sys, 'argv', ['run_hosted.py', 'check']), self.assertRaises(engine.Refused):
                hosted.main()
            self.assertEqual(calls, ['public'])
            signer.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
