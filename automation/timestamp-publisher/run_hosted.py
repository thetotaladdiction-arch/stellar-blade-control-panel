"""Linux hosted transport only; production policy/signing uses unchanged publisher APIs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import urllib.request

HOME = Path(__file__).resolve().parent
REPO_URL = 'https://github.com/thetotaladdiction-arch/stellar-blade-control-panel.git'
GIT = '/usr/bin/git'
MAX_OUTPUT = 2 * 1024**2


def bounded_json(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_OUTPUT + 1)
    if len(raw) > MAX_OUTPUT:
        raise ValueError('bounded JSON refused')
    return json.loads(raw)


def load_engine():
    pins = bounded_json(HOME / 'SOURCE-PINS.json')['files']
    expected_source = {row['relative'] for row in pins if row['relative'].startswith('source/')}
    actual_source = {path.relative_to(HOME).as_posix() for path in (HOME / 'source').rglob('*') if path.is_file()}
    if actual_source != expected_source:
        raise ValueError('closed source inventory refused')
    for row in pins:
        path = HOME / row['relative']
        if path.is_symlink() or not path.resolve().is_relative_to(HOME):
            raise ValueError('source path refused')
        if not 0 <= row['bytes'] <= MAX_OUTPUT:
            raise ValueError('source bound refused')
        with path.open('rb') as stream:
            raw = stream.read(row['bytes'] + 1)
        if len(raw) != row['bytes'] or hashlib.sha256(raw).hexdigest() != row['sha256']:
            raise ValueError('source pin refused')
    sys.path[:0] = [str(HOME), str(HOME / 'source')]
    import policy_engine
    return policy_engine


def child_limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024**2, 16 * 1024**2))
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 60))


class Git:
    def __init__(self, directory):
        self.directory = directory
        directory.mkdir(mode=0o700)
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(directory), 'LANG': 'C.UTF-8',
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
                    'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false',
                    'GIT_ATTR_NOSYSTEM': '1', 'GIT_LFS_SKIP_SMUDGE': '1'}
        self.run(['init', '--bare', str(directory / 'repo.git')])
        self.repo = directory / 'repo.git'

    def run(self, arguments, data=None, token=None):
        env = dict(self.env)
        if token is not None:
            # Authentication only in this child's environment, never argv/URL or logs.
            auth = base64.b64encode(('x-access-token:' + token).encode()).decode()
            env.update(GIT_CONFIG_COUNT='1',
                GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
                GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + auth)
        prefix = [GIT, '-c', 'core.hooksPath=/dev/null', '-c', 'credential.helper=',
                  '-c', 'protocol.file.allow=never', '-c', 'protocol.ext.allow=never',
                  '-c', 'gc.auto=0', '-c', 'maintenance.auto=false']
        if hasattr(self, 'repo'):
            prefix += ['-C', str(self.repo)]
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            child = subprocess.Popen(prefix + arguments, stdin=subprocess.PIPE,
                stdout=out, stderr=err, env=env, start_new_session=True, preexec_fn=child_limits)
            try:
                child.communicate(data, timeout=30)
            except BaseException:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait(timeout=5)
                raise
            out.seek(0)
            result = out.read(MAX_OUTPUT + 1)
            if child.returncode or len(result) > MAX_OUTPUT:
                raise RuntimeError('bounded Git operation refused')
            return result

    def tip(self, ref):
        raw = self.run(['ls-remote', '--refs', REPO_URL, ref]).decode('ascii')
        match = re.fullmatch(r'([0-9a-f]{40})\t' + re.escape(ref) + r'\n', raw)
        if match is None:
            raise ValueError('exact remote ref required')
        return match[1]

    def snapshot(self, parent, ref, engine, policy):
        self.run(['fetch', '--no-tags', '--depth=1', REPO_URL, ref])
        engine.expected_parent(self.run(['rev-parse', 'FETCH_HEAD']).decode().strip(), parent)
        raw = self.run(['ls-tree', '-r', '-z', '-l', parent])
        rows = raw.rstrip(b'\0').split(b'\0')
        engine.need(len(rows) == len(policy['expected_files']) <= 64)
        files = {}
        for row in rows:
            header, name = row.split(b'\t', 1)
            mode, kind, oid, size = header.split()
            path = name.decode('ascii')
            engine.need(mode == b'100644' and kind == b'blob')
            engine.need(path in policy['expected_files'] and path not in files)
            engine.need(size.isdigit() and 0 < int(size) <= 512000)
            blob = self.run(['cat-file', 'blob', oid.decode('ascii')])
            engine.need(len(blob) == int(size))
            engine.need(engine.git_operator._object_id('blob', blob) == oid.decode('ascii'))
            files[path] = blob
        engine.expected_parent(self.tip(ref), parent)
        return files

    def write_candidate(self, files, parent, engine):
        nested = {}
        for path, raw in sorted(files.items()):
            oid = self.run(['hash-object', '-w', '--stdin'], raw).decode().strip()
            engine.need(oid == engine.git_operator._object_id('blob', raw))
            node = nested
            parts = path.split('/')
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = oid
        def tree(node):
            entries = []
            for name, value in sorted(node.items()):
                directory = isinstance(value, dict)
                oid = tree(value) if directory else value
                entries.append(('040000 tree ' if directory else '100644 blob ') + oid + '\t' + name + '\n')
            return self.run(['mktree'], ''.join(entries).encode('ascii')).decode().strip()
        oid = tree(nested)
        engine.need(oid == engine.git_operator._tree_id(files))
        raw = engine.git_operator._commit_bytes(oid, parent)
        commit = self.run(['hash-object', '-t', 'commit', '-w', '--stdin'], raw).decode().strip()
        engine.need(commit == engine.git_operator._object_id('commit', raw))
        return commit


def anonymous_exact(files, commit, policy, run_id):
    for path, expected in files.items():
        url = 'https://raw.githubusercontent.com/' + policy['repository'] + '/' + commit + '/' + path
        request = urllib.request.Request(url + '?publisher_run=' + run_id,
                                         headers={'Cache-Control': 'no-cache'})
        with urllib.request.urlopen(request, timeout=15) as response:
            if response.status != 200 or not response.url.startswith('https://raw.githubusercontent.com/'):
                raise ValueError('anonymous origin refused')
            actual = response.read(len(expected) + 1)
        if actual != expected:
            raise ValueError('anonymous bytes differ')


def main():
    # Remove private input from the environment before any child process/import.
    pem = os.environ.pop('AERONEUS_TIMESTAMP_PEM', None)
    token = os.environ.pop('AERONEUS_PUSH_TOKEN', None)
    if sys.platform != 'linux' or sys.argv[1:] not in (['check'], ['publish']):
        raise ValueError('fixed Linux hosted entry required')
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    engine = load_engine()
    policy = bounded_json(HOME / 'policy.json')
    event = bounded_json(os.environ['GITHUB_EVENT_PATH'])
    mode = sys.argv[1]
    engine.context(os.environ, event, policy, mode=mode)
    if mode == 'check':
        engine.need(pem is None and token is None)
    engine.need(os.environ.get('RUNNER_DEBUG') != '1' and
                not os.environ.get('ACTIONS_STEP_DEBUG') and not os.environ.get('ACTIONS_RUNNER_DEBUG'))
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    engine.need(re.fullmatch('[0-9]{1,24}', run_id) is not None)
    base = Path(os.environ['RUNNER_TEMP']) / ('aeroneus-timestamp-' + run_id)
    base.mkdir(mode=0o700, exist_ok=True)
    engine.need(not base.is_symlink())
    git = Git(base / mode)
    ref = policy['metadata_ref']
    parent = git.tip(ref)
    files = git.snapshot(parent, ref, engine, policy)
    _, _, _, plan = engine.inspect(files, parent, policy, engine.utc())
    if mode == 'check':
        engine.need(pem is None and token is None)
        with (base / 'plan.json').open('x') as out:
            json.dump(plan, out, sort_keys=True)
        with open(os.environ['GITHUB_OUTPUT'], 'a') as out:
            out.write('decision=' + plan['decision'] + '\n')
        print(json.dumps(plan, sort_keys=True))
        if plan['decision'] in ('GENUINE_STAGE_SUCCESSOR_REQUIRED', 'ROOT_SUCCESSOR_REQUIRED'):
            raise RuntimeError('genuine child successor required')
        return
    previous = bounded_json(base / 'plan.json')
    engine.expected_parent(parent, previous['parent'])
    engine.need(plan['tree'] == previous['tree'] and plan['decision'] == 'RENEW_DUE')
    engine.need(os.environ.get('TIMESTAMP_KEY_HOSTING_APPROVED') == 'true')
    consent = policy['hosting_consent_record']
    engine.need(isinstance(consent, dict) and set(consent) == {'id', 'sha256'})
    engine.need(isinstance(consent['id'], str) and bool(consent['id']))
    engine.need(re.fullmatch('[0-9a-f]{64}', consent['sha256']) is not None)
    engine.need(isinstance(token, str) and 0 < len(token) < 4096)
    signer = engine.signer_from_memory(pem, policy)
    pem = None
    result, after = engine.candidate(files, parent, policy, signer, engine.utc())
    signer = None
    commit = git.write_candidate(result, parent, engine)
    engine.expected_parent(git.tip(ref), parent)
    # Fresh genuine API verification immediately before expected-parent CAS.
    engine.inspect(result, parent, policy, engine.utc())
    git.run(['push', '--porcelain', '--force-with-lease=' + ref + ':' + parent,
             REPO_URL, commit + ':' + ref], token=token)
    token = None
    engine.expected_parent(git.tip(ref), commit)
    observed = git.snapshot(commit, ref, engine, policy)
    engine.need(observed == result)
    engine.inspect(observed, commit, policy, engine.utc())
    anonymous_exact(result, commit, policy, run_id)
    engine.expected_parent(git.tip(ref), commit)
    summary = dict(status='PUBLISHED_ANONYMOUS_EXACT', commit=commit, previous=parent,
                   timestamp_version=after['timestamp_version'], expires=after['expires'], files=len(result))
    with (base / 'RESULT.json').open('x') as out:
        json.dump(summary, out, sort_keys=True)
    print(json.dumps(summary, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except BaseException as error:
        # No messages, traceback, locals, environment dump, private bytes or Git output.
        print('TIMESTAMP_PUBLISHER_REFUSED:' + type(error).__name__)
        raise SystemExit(1)
