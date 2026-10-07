# Portable panel rebuild steps

Selection: 37 compiled project Python modules (861,046 original bytes), 120 actual bundled own assets (1,077,973 bytes), 7 additional build inputs. All 164 selected files were matched to the frozen273 source table and actual archive proof; unused artwork/private development trees are excluded. Current source retains the exact PyInstaller spec and runtime-compatibility filters. Source comment redactions are recorded by original/support hashes; Python AST and recursively compiled bytecode logic equality was checked for 42 Python/spec files. This is not a byte-identical rebuild promise.

Use Windows x64, Python 3.14.6, PySide6/shiboken6/PySide6-Essentials/PySide6-Addons6.11.1, PyInstaller 6.21.0, pyinstaller-hooks-contrib 2026.6, Pillow 12.3.0. These packages and their Windows/MSVC runtime DLLs are external dependencies supplied by their public distributions. The actual EXE uses the matching PySide6 wheel's root runtime-family replacements, as shown in the spec. UE4SS/game executables are not panel build dependencies.

From this snapshot's panel directory in a fresh virtual environment:

```powershell
python -m pip install PySide6==6.11.1 pyinstaller==6.21.0 pyinstaller-hooks-contrib==2026.6 Pillow==12.3.0
$env:PYTHONHASHSEED = '0'
$env:SOURCE_DATE_EPOCH = '1791213637'
$env:SBCHEATGUI_MOD_ROOT = (Get-Location).Path
$env:SBCHEATGUI_ASSET_STAGE = Join-Path (Get-Location).Path 'build-assets'
$env:PYINSTALLER_CONFIG_DIR = Join-Path (Get-Location).Path 'build-cache'
python tools/collect_qt_assets.py --qt-root QtPanel --brand-root assets/brand --output build-assets --manifest build-assets.json
python -m PyInstaller --distpath dist --workpath build-pyinstaller QtPanel/StellarBladeControlPanel.optimized.spec
```

Provided eve.ico and eve-mod-icon-256.png are sufficient build inputs; original artwork source is not required. The icon-generation script remains for recipe inspection only; use the direct-spec build above with the provided icons. Use a fresh `build-assets` output directory; the collector writes the same directory read through SBCHEATGUI_ASSET_STAGE by the spec. The actual collector reports 56 reachable components and zero additional assets; the included DesignSystem/brand artwork is already in the spec's QML tree. Do not point the asset-stage environment variable at unrelated artwork.

The spec emits dist/Stellar Blade Mod Suite.exe. The release uses consumer basename Stellar Blade Control Panel.exe; renaming is a packaging step, not an executable-code change. A packaged software smoke can use QT_QPA_PLATFORM=offscreen and QT_QUICK_BACKEND=software with --smoke, after reviewing the main.py command-line branch. No game/player-file operation is required for compilation.

The direct-spec steps retain the original package runtime filters. They do not depend on the excluded host-specific orchestration scripts. Portable builds may differ in metadata and hashes across paths, operating systems and tool installations. No build of this support snapshot is claimed.
