"""Read-only Linux module smoke; never the production check/publish entry."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPOSITORY = 'thetotaladdiction-arch/stellar-blade-control-panel'
SMOKE_REF = 'refs/heads/aeroneus-timestamp-smoke01'


def main():
    if (sys.argv[1:] or sys.platform != 'linux' or
            sys.version_info[:3] != (3, 14, 0) or platform.machine() != 'x86_64'):
        raise ValueError('fixed Linux smoke runtime required')
    release = platform.freedesktop_os_release()
    if release.get('ID') != 'ubuntu' or release.get('VERSION_ID') != '24.04':
        raise ValueError('Ubuntu24.04 required')
    # Refuse private input by name, without reading or printing any value.
    if any(name in os.environ for name in
           ('AERONEUS_TIMESTAMP_PEM', 'AERONEUS_PUSH_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN')):
        raise ValueError('secret-free smoke required')
    # This authentic PUSH context is distinct from the production SCHEDULE context.
    if (os.environ.get('GITHUB_EVENT_NAME') != 'push' or
            os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or
            os.environ.get('GITHUB_REF') != SMOKE_REF or
            os.environ.get('GITHUB_WORKFLOW_REF') != REPOSITORY +
            '/.github/workflows/aeroneus-timestamp-smoke.yml@' + SMOKE_REF):
        raise ValueError('isolated smoke workflow required')
    source_commit = os.environ.get('GITHUB_SHA', '')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if (re.fullmatch('[0-9a-f]{40}', source_commit) is None or
            re.fullmatch('[0-9]{1,24}', run_id) is None):
        raise ValueError('actual workflow identity required')
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    sys.path.insert(0, str(HERE))
    import run_hosted as hosted
    engine = hosted.load_engine()  # Existing closed inventory and all20 byte pins.
    policy = hosted.bounded_json(HERE / 'policy.json')
    engine.need(policy['repository'] == REPOSITORY)
    engine.need(policy['metadata_ref'] == 'refs/heads/aeroneus-updates')
    engine.need(len(policy['expected_files']) == 11)
    # Existing bounded Git children use a clean environment and no auth/token.
    with tempfile.TemporaryDirectory(prefix='aeroneus-public-smoke-',
                                     dir=os.environ['RUNNER_TEMP']) as temporary:
        git = hosted.Git(Path(temporary) / 'public')
        ref = policy['metadata_ref']
        parent = git.tip(ref)
        files = git.snapshot(parent, ref, engine, policy)
        engine.inspect(files, parent, policy, engine.utc())
        hosted.anonymous_exact(files, parent, policy, run_id)
        engine.expected_parent(git.tip(ref), parent)
        _, _, _, plan = engine.inspect(files, parent, policy, engine.utc())
        # Same child-deadline outcome as production check; never adjust the clock.
        engine.need(plan['decision'] in ('WAIT', 'RENEW_DUE'))
        result = dict(status='PUBLIC_MODULE_SMOKE_PASS', source_commit=source_commit,
                      runtime=dict(python=platform.python_version(), system=sys.platform,
                                   os_id=release['ID'], os_version=release['VERSION_ID'],
                                   machine=platform.machine()),
                      metadata_ref=ref, plan=plan, files=[
                          dict(path=path, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                          for path, raw in sorted(files.items())],
                      production_context_check_executed=False,
                      signing_or_push_executed=False,
                      custody_or_publication_authority_proven=False)
    # Emit only public evidence after the owned temporary repository is removed.
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        print('PUBLIC_MODULE_SMOKE_REFUSED:' + type(error).__name__)
        raise SystemExit(1)
