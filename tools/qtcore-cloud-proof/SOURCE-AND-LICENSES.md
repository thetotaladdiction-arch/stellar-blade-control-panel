# Qt 6.11.1 Core compatibility proof

This package contains a modified shared Qt Core library, its debugging symbols,
file evidence, and corresponding source. It is a build proof, not a product release.
No application startup, DLL loading, marker invocation or native tests are claimed.

The vendor archive is retained unmodified, identified in pins.json by official
URL, size and SHA256. The only source change inserts qglobal-insertion.txt after
the unique LF-delimited QT_BEGIN_NAMESPACE in src/corelib/global/qglobal.cpp.
The preimage and postimage hashes are mandatory. The added C export returns a
fixed proof marker; the modification is dated 2026-10-24 in the source comment.

To reconstruct from this artifact, use preinstalled Python 3.12 or later:

    python -I -B build_verify.py --reconstruct NEW_DIRECTORY

Run this from corresponding-source or give the script's full path. It reads the
included archive beside itself and creates a new source directory. It does not
download, configure, compile or install. The complete vendor tree includes Qt's
third-party sources, copyright notices, REUSE metadata and licensing information.
The artifact also retains Qt's LICENSES directory separately. Preserve all of it.

The exact configure/build command is in audit/CONFIGURE-ARGV.json and the script.
It uses preinstalled MSVC 14.51.36231, SDK 10.0.26100.0, CMake, Ninja and Python;
release/shared/force-debug-info/headersclean, bundled zlib, Windows SDK ICU,
and required C++/WinRT support matching the original library's three factory-cache
exports. The selected SDK's preinstalled projection header is checked and its
include directory is added only if vcvars omitted it. MSVC 19.51 rejects the SDK's
C++17 experimental-coroutine include with STL1011. The build explicitly defines
Microsoft's _SILENCE_EXPERIMENTAL_COROUTINE_DEPRECATION_WARNINGS compatibility
macro, retaining Qt's C++17 mode and the SDK headers. This suppresses only that
deprecation diagnostic; the WinRT compile/link test, ABI checks and three required
exports still must pass. No header patch, forced feature-test result or installer.
There are no examples/tests, and only the Core target with two compiler workers. The actual
CMake configuration must be RelWithDebInfo with the dynamic release CRT (/MD).
Exact mode pins compiler component hashes; other tool identities/versions are
audited. An explicit --compiler-policy compatible-14.51 invocation instead accepts
one installed 14.51 x64 toolset and records its actual identities/hashes separately
in the proof. It never silently changes the default exact policy. Consult the
recorded policy and observed version before rebuilding. No claim of a byte-identical
local build is made. Qt configure may run feature probes; these are not native
application tests or proof that a receiver can load the modified library.

Qt Core is used under the applicable Qt LGPLv3 option, with third-party terms
retained. Keep the LGPL/GPL texts and notices, permit replacement/relinking and
the reverse engineering needed to debug modifications under the applicable terms,
and provide the exact corresponding modified source when distributing binaries.
The source archive plus exact insertion and build recipe are included here rather
than relying solely on a vendor download link. No Qt GUI or other Qt runtime
module is distributed by this proof. Microsoft SDK/CRT files are not redistributed.

Official requirements: https://www.qt.io/development/open-source-lgpl-obligations
Official source: https://download.qt.io/official_releases/qt/6.11/6.11.1/submodules/

A one-day Actions artifact is temporary transport, not durable fulfillment of a
future product distribution's source obligations. Root must retain this complete
source/license package alongside any retained or redistributed binary and review
the final distribution obligations. This proof does not authorize production use.
