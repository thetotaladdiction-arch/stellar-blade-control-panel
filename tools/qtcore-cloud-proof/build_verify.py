"""QtCore proof: cloud-only build, portable source reconstruction, no DLL execution.

Only --source-check is permitted on a normal workstation. No third-party modules.
The artifact contains the original Qt archive plus the exact additive insertion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
REPO = "thetotaladdiction-arch/stellar-blade-control-panel"
REF = "refs/heads/codex/qtcore-cloud-proof-20261025"
ARCHIVE_ROOT = "qtbase-everywhere-src-6.11.1"
LIMIT = 384 * 1024**2
LOG_LIMIT = 16 * 1024**2


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")


def load(path):
    need(path.stat().st_size <= 32 * 1024**2, "JSON exceeds bound")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def row(path, base):
    return {"path": path.relative_to(base).as_posix(), "bytes": path.stat().st_size,
            "sha256": sha(path)}


def run(args, cwd, env, log, seconds=300, allowed=(0,)):
    # Logs are bounded while running. Hosted job timeout is the outer process-tree bound.
    started = time.monotonic()
    with log.open("xb") as out:
        child = subprocess.Popen(args, cwd=cwd, env=env, stdout=out, stderr=out)
        try:
            while child.poll() is None:
                need(time.monotonic() - started < seconds, "command timeout: " + log.name)
                need(log.stat().st_size <= LOG_LIMIT, "command log bound: " + log.name)
                time.sleep(0.2)
        except BaseException:
            # Only this cloud-owned child tree; never run on the owner's workstation.
            subprocess.run(["taskkill", "/PID", str(child.pid), "/T", "/F"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            child.wait(timeout=20)
            raise
    need(log.stat().st_size <= LOG_LIMIT, "completed log bound")
    need(child.returncode in allowed, "command failed: " + log.name + " exit=" + str(child.returncode))
    return log.read_text(encoding="utf-8", errors="replace")


def source_check():
    p = load(HERE / "pins.json")
    insertion = (HERE / "qglobal-insertion.txt").read_bytes()
    need(p["qt_version"] == "6.11.1" and p["msvc"] == "14.51.36231", "unexpected pin policy")
    need(p["archive_bytes"] == 50648500 and len(insertion) == 284, "source size pins")
    need(p["qglobal_post_bytes"] - p["qglobal_pre_bytes"] == len(insertion), "patch size")
    need(b"\r" not in insertion and insertion.count(p["marker_export"].encode()) == 1, "exact insertion")
    for key in ("archive_sha256", "qglobal_pre_sha256", "qglobal_post_sha256"):
        need(re.fullmatch("[0-9a-f]{64}", p[key]), "invalid SHA pin")
    need(set(p["compiler_sha256"]) == {"cl.exe", "link.exe", "c1xx.dll", "c2.dll"}, "compiler pins")
    return p


def cloud_guard():
    need(os.name == "nt" and os.environ.get("GITHUB_ACTIONS") == "true", "build allowed only in GitHub Actions Windows")
    for k, v in {"RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Windows",
                 "RUNNER_ARCH": "X64", "GITHUB_REPOSITORY": REPO, "GITHUB_REF": REF,
                 "GITHUB_EVENT_NAME": "push"}.items():
        need(os.environ.get(k) == v, "cloud guard failed: " + k)
    event = load(Path(os.environ["GITHUB_EVENT_PATH"]))
    need(event["repository"]["private"] is False and event["repository"]["full_name"] == REPO,
         "public repository required")


def toolchain(p, work, audit, policy):
    env = {key.upper(): value for key, value in os.environ.items()}
    for key in list(env):
        if key.upper() in {"CL", "_CL_", "LINK", "_LINK_", "QT_HOST_PATH", "QT6_DIR",
                           "CMAKE_PREFIX_PATH", "QMAKESPEC", "CMAKE_TOOLCHAIN_FILE"}:
            del env[key]
    locator = Path(env["PROGRAMFILES(X86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    need(locator.is_file(), "preinstalled vswhere missing; no installer permitted")
    raw = subprocess.check_output([str(locator), "-all", "-products", "*", "-format", "json"],
                                  env=env, timeout=30)
    installations = json.loads(raw.decode("utf-8-sig"))
    inventory, candidates, alternatives = [], [], []
    for vs in installations:
        base = Path(vs["installationPath"])
        tools = base / "VC/Tools/MSVC"
        versions = sorted(d.name for d in tools.iterdir() if d.is_dir()) if tools.is_dir() else []
        inventory.append({"visual_studio": vs["installationVersion"], "toolsets": versions})
        if p["msvc"] in versions:
            candidates.append((p["msvc"], base))
        alternatives += [(v, base) for v in versions if re.fullmatch(r"14\.51\.[0-9]+", v)]
    save(audit / "TOOLSET-INVENTORY.json", {"requested_msvc": p["msvc"], "installed": inventory,
         "runner_image": os.environ.get("ImageVersion"), "runner_image_os": os.environ.get("ImageOS"),
         "runtime_version_is_not_compiler_version": True, "selected_policy": policy})
    if not candidates and policy == "compatible-14.51":
        candidates = sorted(alternatives, key=lambda item: tuple(map(int, item[0].split("."))), reverse=True)
    need(candidates, "EXACT_TOOLSET_UNAVAILABLE: 14.51.36231 (or explicitly selected 14.51 family); see TOOLSET-INVENTORY.json. No installation.")
    selected_msvc, base = candidates[0]
    compiler = base / "VC/Tools/MSVC" / selected_msvc / "bin/Hostx64/x64"
    observed = {}
    for name, expected in p["compiler_sha256"].items():
        path = compiler / name
        need(path.is_file(), "compiler component missing: " + name)
        observed[name] = sha(path)
    exact = selected_msvc == p["msvc"] and observed == p["compiler_sha256"]
    save(audit / "COMPILER-HASHES.json", {"observed_toolset": selected_msvc, "observed_sha256": observed,
         "reference_sha256": p["compiler_sha256"], "exact_reference_compiler": exact, "selected_policy": policy})
    need(exact or policy == "compatible-14.51", "EXACT_COMPILER_BYTES_DIFFER: explicit separate review required")
    p = dict(p, msvc=selected_msvc, compiler_policy=policy, exact_reference_compiler=exact)
    vcvars = base / "VC/Auxiliary/Build/vcvarsall.bat"
    # Environment output stays in memory; never archive a token-bearing environment dump.
    command = f'call "{vcvars}" amd64 {p["sdk"]} -vcvars_ver={p["msvc"]} >nul && set'
    raw = subprocess.check_output(f'"{env["COMSPEC"]}" /d /s /c "{command}"', env=env, timeout=60)
    for line in raw.decode("utf-8", errors="replace").splitlines():
        key, sep, value = line.partition("=")
        if sep and key:
            env[key.upper()] = value
    need(env.get("VCTOOLSVERSION", "").rstrip("\\/") == p["msvc"], "vcvars selected a different MSVC")
    need(env.get("WINDOWSSDKVERSION", "").rstrip("\\/") == p["sdk"], "vcvars selected a different SDK")
    need(Path(shutil.which("cl.exe", path=env["PATH"])).resolve() == (compiler / "cl.exe").resolve(), "cl PATH differs")
    sdk = Path(env["WINDOWSSDKDIR"])
    selected = {"cl": compiler / "cl.exe", "dumpbin": compiler / "dumpbin.exe",
                "rc": sdk / "bin" / p["sdk"] / "x64/rc.exe",
                "mt": sdk / "bin" / p["sdk"] / "x64/mt.exe"}
    for name in ("cmake", "ninja"):
        found = shutil.which(name, path=env["PATH"])
        need(found, "preinstalled tool missing: " + name)
        selected[name] = Path(found)
    for name, path in selected.items():
        need(path.is_file(), "selected tool missing: " + name)
    for suffix in ("Include/" + p["sdk"] + "/um/icu.h", *(
            "Lib/" + p["sdk"] + "/um/x64/" + n for n in ("icu.lib", "icuuc.lib", "icuin.lib"))):
        need((sdk / suffix).is_file(), "Windows SDK ICU input missing: " + suffix)
    save(audit / "TOOLS.json", {"msvc": p["msvc"], "sdk": p["sdk"], "arch": "x64",
         "python": sys.version, "tools": {k: {"path": str(v), "sha256": sha(v)} for k, v in selected.items()}})
    compiler_text = run([str(selected["cl"]), "/Bv"], work, env,
                        audit / "compiler-version.txt", allowed=(0, 2))
    need(re.search(r"\bVersion 19\.51\.[0-9.]+ for x64\b", compiler_text),
         "actual compiler banner is not MSVC 19.51 x64")
    for name in ("cmake", "ninja"):
        run([str(selected[name]), "--version"], work, env, audit / (name + "-version.txt"))
    return env, selected, p


def extract_patch(archive, source, p):
    need(archive.stat().st_size == p["archive_bytes"] and sha(archive) == p["archive_sha256"], "Qt archive pin mismatch")
    source.mkdir()
    seen, total = set(), 0
    # Only the pinned vendor archive, regular files/directories, no links or traversal.
    with tarfile.open(archive, "r|xz") as tar:
        for count, member in enumerate(tar, 1):
            parts = member.name.rstrip("/").split("/")
            need(count <= 100000 and parts[0] == ARCHIVE_ROOT, "archive count/root")
            need(member.isdir() or member.isfile(), "archive links/devices refused")
            need(all(x and x not in (".", "..") and not x.endswith((" ", ".")) and
                     not re.search(r'[\\:\x00-\x1f<>"|?*]', x) and
                     not re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', x)
                     for x in parts), "unsafe archive name")
            key = "/".join(parts).casefold()
            need(key not in seen, "duplicate archive member")
            seen.add(key)
            total += member.size
            need(0 <= member.size <= 128 * 1024**2 and total <= 1024**3, "archive byte bound")
            dest = source.joinpath(*parts)
            if member.isdir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(member) as inp, dest.open("xb") as out:
                    shutil.copyfileobj(inp, out, 65536)
                need(dest.stat().st_size == member.size, "short archive member")
    qglobal = source / ARCHIVE_ROOT / "src/corelib/global/qglobal.cpp"
    need(qglobal.stat().st_size == p["qglobal_pre_bytes"] and sha(qglobal) == p["qglobal_pre_sha256"], "qglobal preimage")
    before = qglobal.read_bytes()
    anchor = b"\nQT_BEGIN_NAMESPACE\n"
    need(before.count(anchor) == 1, "qglobal unique insertion point")
    after = before.replace(anchor, anchor + (HERE / "qglobal-insertion.txt").read_bytes(), 1)
    need(len(after) == p["qglobal_post_bytes"] and hashlib.sha256(after).hexdigest() == p["qglobal_post_sha256"], "qglobal postimage")
    qglobal.write_bytes(after)
    return source / ARCHIVE_ROOT


def configure(src, build, p, env, tools, audit):
    query = build / ".cmake/api/v1/query"
    query.mkdir(parents=True)
    for kind in ("codemodel-v2", "cache-v2", "toolchains-v1"):
        (query / kind).write_bytes(b"")
    args = [str(src / "configure.bat"), "-release", "-shared", "-force-debug-info", "-headersclean",
            "-nomake", "examples", "-nomake", "tests", "-qt-zlib", "-feature-winsdkicu",
            "-prefix", str(build.parent / "unused-install-prefix"), "--", "-G", "Ninja",
            "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            "-DCMAKE_AUTOGEN_PARALLEL=2", "-DCMAKE_JOB_POOLS=qt_compile=2;qt_link=1",
            "-DCMAKE_JOB_POOL_COMPILE=qt_compile", "-DCMAKE_JOB_POOL_LINK=qt_link",
            "-DCMAKE_EXPORT_PACKAGE_REGISTRY=OFF", "-DCMAKE_EXPORT_NO_PACKAGE_REGISTRY=ON",
            "-DCMAKE_FIND_USE_PACKAGE_REGISTRY=OFF", "-DCMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY=OFF",
            "-DFETCHCONTENT_FULLY_DISCONNECTED=ON", "-DFETCHCONTENT_UPDATES_DISCONNECTED=ON",
            "-DPython_EXECUTABLE=" + Path(sys.executable).as_posix(),
            "-DPython3_EXECUTABLE=" + Path(sys.executable).as_posix()]
    for key, name in (("CMAKE_MAKE_PROGRAM", "ninja"), ("CMAKE_RC_COMPILER", "rc"), ("CMAKE_MT", "mt"),
                      ("CMAKE_C_COMPILER", "cl"), ("CMAKE_CXX_COMPILER", "cl")):
        args.append("-D" + key + "=" + tools[name].as_posix())
    save(audit / "CONFIGURE-ARGV.json", args)
    run(f'"{env["COMSPEC"]}" /d /s /c "{subprocess.list2cmdline(args)}"', build, env,
        audit / "configure.txt", seconds=720)


def cache_value_matches(actual, expected):
    # Qt configure writes FALSE for -nomake while other CMake options use OFF.
    # Accept equivalent explicit booleans, never a missing/unknown value.
    if expected == "ON":
        return isinstance(actual, str) and actual.upper() in {"ON", "TRUE", "1"}
    if expected == "OFF":
        return isinstance(actual, str) and actual.upper() in {"OFF", "FALSE", "0"}
    return actual == expected


def verify_config(src, build, p, tools, audit):
    cache = {}
    for line in (build / "CMakeCache.txt").read_text(encoding="utf-8-sig").splitlines():
        if not line or line.startswith(("#", "//")):
            continue
        m = re.fullmatch(r"([^:=]+):[^=]+=(.*)", line)
        need(m and m[1] not in cache, "invalid/duplicate CMake cache key")
        cache[m[1]] = m[2]
    wanted = {"CMAKE_GENERATOR": "Ninja", "CMAKE_BUILD_TYPE": "RelWithDebInfo",
              "BUILD_SHARED_LIBS": "ON", "QT_FEATURE_winsdkicu": "ON", "QT_FEATURE_system_zlib": "OFF",
              "QT_BUILD_TESTS": "OFF", "QT_BUILD_EXAMPLES": "OFF",
              "CMAKE_MSVC_RUNTIME_LIBRARY": "MultiThreadedDLL",
              "CMAKE_EXPORT_PACKAGE_REGISTRY": "OFF", "CMAKE_EXPORT_NO_PACKAGE_REGISTRY": "ON",
              "CMAKE_FIND_USE_PACKAGE_REGISTRY": "OFF", "CMAKE_FIND_USE_SYSTEM_PACKAGE_REGISTRY": "OFF",
              "FETCHCONTENT_FULLY_DISCONNECTED": "ON", "FETCHCONTENT_UPDATES_DISCONNECTED": "ON"}
    for key, value in wanted.items():
        need(cache_value_matches(cache.get(key), value), "CMake cache contract failed: " + key)
    for key, path in {"CMAKE_HOME_DIRECTORY": src, "CMAKE_C_COMPILER": tools["cl"],
                      "CMAKE_CXX_COMPILER": tools["cl"], "CMAKE_RC_COMPILER": tools["rc"],
                      "CMAKE_MT": tools["mt"], "CMAKE_MAKE_PROGRAM": tools["ninja"]}.items():
        need(Path(cache.get(key, "")).resolve() == path.resolve(), "CMake selected different tool/source: " + key)
    reply = build / ".cmake/api/v1/reply"
    indices = sorted(reply.glob("index-*.json"))
    need(len(indices) == 1, "expected one fresh CMake File API index")
    index = load(indices[0])
    def object_file(kind):
        objs = [x for x in index["objects"] if x["kind"] == kind]
        need(len(objs) == 1, "File API kind missing: " + kind)
        name = objs[0]["jsonFile"]
        need(re.fullmatch(r"[A-Za-z0-9_.-]+\.json", name), "unsafe File API name")
        return reply / name
    model = load(object_file("codemodel"))
    chains = load(object_file("toolchains"))["toolchains"]
    for language in ("C", "CXX"):
        actual = [c["compiler"] for c in chains if c["language"] == language]
        need(len(actual) == 1 and actual[0]["id"] == "MSVC" and
             re.match(r"19\.51\.", actual[0]["version"]) and
             Path(actual[0]["path"]).resolve() == tools["cl"].resolve(),
             "actual CMake compiler family/path differs: " + language)
    need(len(model["configurations"]) == 1 and model["configurations"][0]["name"] == "RelWithDebInfo", "actual codemodel configuration")
    cores = [t for t in model["configurations"][0]["targets"] if t["name"] == "Core"]
    need(len(cores) == 1, "Core target missing")
    need(re.fullmatch(r"[A-Za-z0-9_.-]+\.json", cores[0]["jsonFile"]), "unsafe target reply")
    target_path = reply / cores[0]["jsonFile"]
    target = load(target_path)
    need(target["type"] == "SHARED_LIBRARY" and
         "bin/Qt6Core.dll" in [a["path"].replace("\\", "/") for a in target["artifacts"]], "actual shared Core artifact")
    for group in target["compileGroups"]:
        if group["language"] not in ("C", "CXX"):
            continue
        flags = " ".join(f["fragment"] for f in group["compileCommandFragments"])
        need(re.search(r"(?:^|\s)[/-]MD(?:\s|$)", flags) and
             not re.search(r"(?:^|\s)[/-](?:MDd|MTd?|MP\d*)(?:\s|$)", flags), "Core must use /MD without /MP")
    commands = load(build / "compile_commands.json")
    qglobal = [c for c in commands if Path(c["file"]).name == "qglobal.cpp" and
               "Core.dir" in c.get("command", "")]
    need(len(qglobal) == 1, "actual Core qglobal compile command absent/ambiguous")
    need(not any(re.search(r"(?:^|\s)[/-]MP\d*(?:\s|$)", c.get("command", "")) for c in commands), "unbounded compiler /MP")
    save(audit / "CONFIGURATION-PROOF.json", {"cache_contract": wanted,
         "actual_cache_values": {k: cache[k] for k in wanted}, "configuration": "RelWithDebInfo",
         "target_type": target["type"], "qglobal_compile_command": qglobal[0], "native_tests_run": False})
    for path in (build / "CMakeCache.txt", build / "config.opt", build / "config.summary",
                 build / "compile_commands.json", target_path, indices[0],
                 object_file("codemodel"), object_file("cache"), object_file("toolchains")):
        need(path.is_file(), "required configure evidence absent: " + path.name)
        shutil.copy2(path, audit / path.name)


def pe_check(dll, p):
    data = dll.read_bytes()
    need(len(data) <= 128 * 1024**2 and data[:2] == b"MZ", "DLL file bound/header")
    pe = struct.unpack_from("<I", data, 60)[0]
    need(data[pe:pe + 4] == b"PE\0\0", "PE signature")
    machine, count, _, _, _, opt_size, flags = struct.unpack_from("<HHIIIHH", data, pe + 4)
    need(machine == 0x8664 and flags & 0x2000 and 1 <= count <= 32, "actual AMD64 DLL")
    opt = pe + 24
    need(struct.unpack_from("<H", data, opt)[0] == 0x20b, "PE32+ required")
    export, size = struct.unpack_from("<II", data, opt + 112)
    sections = []
    for i in range(count):
        off = opt + opt_size + i * 40
        vs, va, rawsize, raw = struct.unpack_from("<IIII", data, off + 8)
        chars = struct.unpack_from("<I", data, off + 36)[0]
        sections.append((va, rawsize, raw, chars))
    def rva(value, n):
        matches = [(raw + value - va, chars) for va, size, raw, chars in sections
                   if va <= value and value + n <= va + size]
        need(len(matches) == 1 and matches[0][0] + n <= len(data), "PE RVA bound")
        return matches[0]
    nf, nn, funcs, names, ordinals = struct.unpack_from("<IIIII", data, rva(export, 40)[0] + 20)
    need(0 < nn <= nf <= 65536, "PE export count")
    matches = []
    for i in range(nn):
        nr = struct.unpack_from("<I", data, rva(names + i * 4, 4)[0])[0]
        name = bytearray()
        for j in range(512):
            c = data[rva(nr + j, 1)[0]]
            if not c:
                break
            name.append(c)
        else:
            raise RuntimeError("unterminated export")
        if name == p["marker_export"].encode():
            ordinal = struct.unpack_from("<H", data, rva(ordinals + i * 2, 2)[0])[0]
            need(ordinal < nf, "export ordinal bound")
            function = struct.unpack_from("<I", data, rva(funcs + ordinal * 4, 4)[0])[0]
            need(not export <= function < export + size and rva(function, 1)[1] & 0x20000000,
                 "marker forwarded or not executable")
            matches.append(function)
    need(len(matches) == 1 and p["marker_value"].encode() + b"\0" in data, "marker export/string missing")
    return {"machine": "AMD64", "marker_rva": matches[0], "marker_called": False, "dll_loaded": False}


def build(p, policy):
    cloud_guard()  # Never configure, compile or download before this guard.
    run_id, attempt = os.environ["GITHUB_RUN_ID"], os.environ["GITHUB_RUN_ATTEMPT"]
    need(run_id.isdigit() and attempt.isdigit(), "run identity")
    work = Path(os.environ["RUNNER_TEMP"]) / ("qtcore-proof-" + run_id + "-" + attempt)
    work.mkdir(exist_ok=False)
    artifact, audit = work / "artifact", work / "audit"
    audit.mkdir()
    artifact.mkdir()
    started = time.monotonic()
    try:
        env, tools, p = toolchain(p, work, audit, policy)
        need(shutil.disk_usage(work).free >= 12 * 1024**3, "runner disk headroom below 12 GiB")
        archive = work / p["archive_name"]
        with urllib.request.urlopen(p["source_url"], timeout=60) as inp, archive.open("xb") as out:
            need(inp.url.startswith("https://"), "non-HTTPS download refused")
            received = 0
            while chunk := inp.read(65536):
                received += len(chunk)
                need(received <= p["archive_bytes"] and time.monotonic() - started < 300, "download byte/time bound")
                out.write(chunk)
        src = extract_patch(archive, work / "source", p)
        build_dir = work / "qt-build"
        configure(src, build_dir, p, env, tools, audit)
        verify_config(src, build_dir, p, tools, audit)
        run([str(tools["cmake"]), "--build", str(build_dir), "--target", "Core", "--parallel", "2"],
            work, env, audit / "core.txt", seconds=1800)
        # The build must not silently change the previously checked configuration.
        need(sha(build_dir / "CMakeCache.txt") == sha(audit / "CMakeCache.txt"), "cache changed during build")
        need(sha(build_dir / "compile_commands.json") == sha(audit / "compile_commands.json"), "compile commands changed during build")
        need(sha(src / "src/corelib/global/qglobal.cpp") == p["qglobal_post_sha256"], "patched source changed")
        for name in ("build.ninja", ".ninja_log"):
            observed_file = build_dir / name
            need(observed_file.is_file() and observed_file.stat().st_size <= LOG_LIMIT, "build audit absent/oversized: " + name)
            shutil.copy2(observed_file, audit / observed_file.name.lstrip("."))
        qconfig = build_dir / "src/corelib/global/qconfig.h"
        if qconfig.is_file():
            need(qconfig.stat().st_size <= LOG_LIMIT, "qconfig audit byte bound")
            shutil.copy2(qconfig, audit / "qconfig.h")
        dll, pdb = build_dir / "bin/Qt6Core.dll", build_dir / "bin/Qt6Core.pdb"
        need(dll.is_file() and pdb.is_file() and 0 < pdb.stat().st_size <= 256 * 1024**2, "DLL/PDB absent or oversized")
        with pdb.open("rb") as symbols:
            need(symbols.read(32).startswith(b"Microsoft C/C++ MSF 7.00"), "PDB signature")
        pe = pe_check(dll, p)
        texts = {}
        for kind in ("headers", "exports", "imports"):
            texts[kind] = run([str(tools["dumpbin"]), "/" + kind, str(dll)], work, env,
                              audit / (kind + ".txt"))
        imports = sorted(set(re.findall(r"(?im)^\s+([A-Za-z0-9_.-]+\.dll)\s*$", texts["imports"])))
        low = [x.lower() for x in imports]
        need(any(x.startswith("vcruntime140") and not x.endswith("d.dll") for x in low), "release dynamic VC runtime import missing")
        need(not any(re.fullmatch(r"(?:vcruntime\d+(?:_\d+)?|msvcp\d+)d\.dll|ucrtbased\.dll", x) for x in low), "debug CRT import")
        need(not any(x.startswith("qt6") for x in low), "unexpected other Qt module import")
        # Pinned Qt Core CMakeLists links icuuc/icuin for winsdkicu, not icu.
        # The Windows SDK exposes the codec API via icuuc.dll (icu.dll is
        # the combined Windows 10 1903+ alternative). The full import report
        # remains evidence; this does not prove runtime loading on a receiver.
        need("icuuc.dll" in low or "icu.dll" in low, "Windows SDK ICU codec import missing")
        proof = {"schema": "QtCoreCloudCompatibilityProofV1", "status": "BUILT_FILE_VERIFIED",
                 "qt_version": p["qt_version"], "msvc": p["msvc"], "sdk": p["sdk"],
                 "compiler_policy": p["compiler_policy"], "exact_reference_compiler": p["exact_reference_compiler"],
                 "configuration": "RelWithDebInfo", "crt": "MD", "pe": pe, "imports": imports,
                 "source_archive_sha256": p["archive_sha256"], "qglobal_post_sha256": p["qglobal_post_sha256"],
                 "commit": os.environ["GITHUB_SHA"], "run_id": run_id, "run_attempt": attempt,
                 "native_tests_run": False, "configure_feature_probes_may_run": True,
                 "receiver_startup_proven": False, "modified_library_load_proven": False,
                 "installed": False, "production_release": False, "byte_identical_local_build_claim": False}
        save(audit / "PROOF.json", proof)
        (artifact / "bin").mkdir()
        shutil.copy2(dll, artifact / "bin/Qt6Core.dll")
        shutil.copy2(pdb, artifact / "bin/Qt6Core.pdb")
        corresponding = artifact / "corresponding-source"
        corresponding.mkdir()
        shutil.copy2(archive, corresponding / archive.name)
        for name in ("build_verify.py", "pins.json", "qglobal-insertion.txt", "SOURCE-AND-LICENSES.md"):
            shutil.copy2(HERE / name, corresponding / name)
        shutil.copytree(src / "LICENSES", artifact / "licenses")
        for name in ("LICENSE.LGPL3", "LICENSE.GPL3", "LICENSE.GPL2", "LGPL_EXCEPTION.txt"):
            if (src / name).is_file():
                shutil.copy2(src / name, artifact / "licenses" / name)
        need(any("LGPL" in f.name for f in (artifact / "licenses").iterdir()), "LGPL license absent")
        # Six rows for Root's payload adapter: binary, symbols, and actual file-proof evidence.
        six = [artifact / "bin/Qt6Core.dll", artifact / "bin/Qt6Core.pdb"]
        shutil.copytree(audit, artifact / "audit")
        six += [artifact / "audit" / n for n in ("headers.txt", "exports.txt", "imports.txt", "PROOF.json")]
        save(artifact / "ARTIFACTS.json", {"schema": 1, "artifacts": [row(f, artifact) for f in six],
             "native_tests_run": False, "modified_library_load_proven": False, "receiver_startup_proven": False})
    except Exception as exc:
        # On failure expose a small inventory/status only, never incomplete binaries or broad logs.
        failure = work / "failure-artifact"
        failure.mkdir()
        for name in ("TOOLSET-INVENTORY.json", "COMPILER-HASHES.json", "TOOLS.json"):
            if (audit / name).is_file():
                shutil.copy2(audit / name, failure / name)
        cache_path = work / "qt-build/CMakeCache.txt"
        if cache_path.is_file() and cache_path.stat().st_size <= 1024**2:
            shutil.copy2(cache_path, failure / "CMakeCache.txt")
        for name in ("compiler-version.txt", "configure.txt", "core.txt", "headers.txt", "exports.txt", "imports.txt"):
            path = audit / name
            if path.is_file():
                with path.open("rb") as inp:
                    inp.seek(max(0, path.stat().st_size - 65536))
                    (failure / ("tail-" + name)).write_bytes(inp.read(65536))
        save(failure / "FAILURE.json", {"status": "FAILED", "reason": str(exc)[:2000],
             "native_tests_run": False, "binary_delivered": False})
        publish_path(failure, p)
        raise
    publish_path(artifact, p)


def publish_path(directory, p):
    files = sorted(x for x in directory.rglob("*") if x.is_file())
    need(len(files) <= 512 and sum(x.stat().st_size for x in files) < p["max_artifact_bytes"] - 1024**2,
         "artifact exceeds 384 MiB/512-file bound; upload refused")
    save(directory / "SHA256-MANIFEST.json", {"files": [row(f, directory) for f in files]})
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8", newline="\n") as out:
        out.write("artifact_dir=" + str(directory) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source-check", action="store_true")
    mode.add_argument("--cloud-build", action="store_true")
    mode.add_argument("--reconstruct", type=Path, metavar="NEW_DIRECTORY")
    parser.add_argument("--compiler-policy", choices=("exact", "compatible-14.51"), default="exact",
                        help="compatible-14.51 is a separate explicitly reviewed policy, never an automatic fallback")
    args = parser.parse_args()
    p = source_check()
    if args.source_check:
        print("PASS: source/pin structure only; no configure, compiler, network or native test executed")
    elif args.reconstruct:
        need(not args.reconstruct.exists(), "reconstruction destination must be new")
        extract_patch(HERE / p["archive_name"], args.reconstruct, p)
        print("Reconstructed exact modified Qt source; nothing configured or built")
    else:
        build(p, args.compiler_policy)


if __name__ == "__main__":
    main()
