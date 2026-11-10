"""Pure timestamp policy. Uses existing authenticated publisher APIs, no key I/O."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re

from publisher import git_operator, public_state, renewal, repository, staging


class Refused(ValueError):
    pass


def need(value):
    if not value:
        raise Refused('publisher boundary refused')


def utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def context(env, event, policy, *, mode='publish'):
    repo = event.get('repository', {})
    need(mode in ('check', 'publish'))
    need(env.get('GITHUB_EVENT_NAME') == 'schedule' or
         (mode == 'check' and env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'))
    need(repo.get('fork') is False)
    need(repo.get('full_name') == policy['repository'] == env.get('GITHUB_REPOSITORY'))
    need(repo.get('default_branch') == policy['default_branch'])
    need(env.get('GITHUB_REF') == 'refs/heads/' + policy['default_branch'])
    need(env.get('GITHUB_WORKFLOW_REF') == policy['repository'] +
         '/.github/workflows/aeroneus-timestamp.yml@refs/heads/' + policy['default_branch'])
    expected = env.get('PUBLISHER_REVIEWED_SOURCE_SHA', '')
    need(re.fullmatch('[0-9a-f]{40}', expected) is not None)
    need(env.get('CHECKED_OUT_PUBLISHER_SHA') == expected)
    need(env.get('GITHUB_RUN_ATTEMPT') == '1')


def inspect(files, parent, policy, now):
    need(set(files) == set(policy['expected_files']))
    need(len(files) <= 64 and sum(map(len, files.values())) <= 2 * 1024**2)
    for row in policy['unchanged_files']:
        raw = files[row['path']]
        need(len(raw) == row['size'] and hashlib.sha256(raw).hexdigest() == row['sha256'])
    state = repository.verify_tree(files=files, expected_parent=parent,
                                  trusted_root_sha256=policy['trusted_root_sha256'], now=now)
    metadata, data, _ = git_operator._extract(files)
    keys = {k: bytes.fromhex(v) for k, v in policy['inner_public_keys_hex'].items()}
    catalog = git_operator._semantic(metadata, data, keys, now, ())
    roles = {r: staging._parse(metadata[r + '.json'], r).signed for r in public_state.ROLES}
    need(all(roles[r].version == v for r, v in policy['fixed_role_versions'].items()))
    need(roles['timestamp'].version >= policy['minimum_timestamp_version'])
    ledger = json.loads(state.ledger_bytes)
    need(ledger['sequence'] >= policy['minimum_ledger_sequence'])
    role = roles['root'].roles['timestamp']
    need(role.threshold == 1 and role.keyids == [policy['timestamp_key_id']])
    # The root API already proves role keys are disjoint. Never request other role signers.
    deadlines = [roles[r].expires for r in ('root', 'targets', 'snapshot')]
    if catalog is not None:
        deadlines.append(catalog.expires_at)
    expiry = roles['timestamp'].expires
    if roles['root'].expires <= now + timedelta(seconds=policy['lifetime_seconds']):
        decision = 'ROOT_SUCCESSOR_REQUIRED'
    elif min(deadlines) <= now + timedelta(seconds=policy['lifetime_seconds']):
        decision = 'GENUINE_STAGE_SUCCESSOR_REQUIRED'
    elif (expiry - now).total_seconds() <= policy['due_seconds']:
        decision = 'RENEW_DUE'
    else:
        decision = 'WAIT'
    return state, metadata, data, {
        'decision': decision, 'parent': parent, 'timestamp_version': roles['timestamp'].version,
        'ledger_sequence': ledger['sequence'], 'expires': expiry.isoformat(),
        'observed_at': now.isoformat(), 'child_deadline': min(deadlines).isoformat(),
        'tree': git_operator._tree_id(files),
    }


def candidate(files, parent, policy, signer, now):
    state, metadata, data, before = inspect(files, parent, policy, now)
    need(before['decision'] == 'RENEW_DUE')
    renewal_result = renewal.create(state, signers=(signer,),
        expires=now + timedelta(seconds=policy['lifetime_seconds']), now=now)
    metadata = dict(metadata, **{'timestamp.json': renewal_result.timestamp_bytes})
    assembled = repository.assemble(previous_tree=files, metadata=metadata, target_data=data,
        expected_parent=parent, trusted_root_sha256=policy['trusted_root_sha256'], now=now,
        ledger_bytes=renewal_result.ledger_bytes)
    result = dict(assembled.files)
    need(set(result) == set(files))
    need({p for p in files if files[p] != result[p]} == {'metadata/timestamp.json', 'public-ledger.json'})
    _, _, _, after = inspect(result, parent, policy, now)
    need(after['timestamp_version'] == before['timestamp_version'] + 1)
    need(after['ledger_sequence'] == before['ledger_sequence'] + 1)
    return result, after


def expected_parent(actual, expected):
    need(re.fullmatch('[0-9a-f]{40}', expected) is not None and actual == expected)


def signer_from_memory(pem, policy):
    # Only called in the separately consented signing step; no files, provider or key export.
    need(isinstance(pem, str) and 0 < len(pem) <= 16384)
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from securesystemslib.signer import CryptoSigner
    signer = CryptoSigner(load_pem_private_key(pem.encode('ascii'), password=None))
    need(signer.public_key.keyid == policy['timestamp_key_id'])
    return signer
