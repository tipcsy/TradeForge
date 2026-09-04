"""A natív gyorsító mag lefordítása (`rust/tfbt` → `tfbt.dll`).

    python tools/build_native.py

⚠ OPCIONÁLIS. A program Rust nélkül is teljes értékűen működik — a natív mag
csak gyorsít. Ha a `cargo` nincs telepítve, ez a szkript ELMONDJA, mit kell
tenni, és 0-val tér vissza: egy hiányzó gyorsítás nem hiba.

⚠ A LEFORDÍTOTT KÖNYVTÁR NEM KERÜL A REPÓBA (bináris, gépfüggő). A forrás igen.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRATE = ROOT / "rust" / "tfbt"


def main() -> int:
    from core import applog
    applog.harden_console()
    # ⚠ A rustup alapbol NEM teszi PATH-ra a cargo-t (`--no-modify-path`), es a
    # felhasznalo sem feltetlenul indit ujra terminalt. Ha a szokasos helyen ott
    # van, hasznaljuk — kulonben egy mar telepitett toolchain mellett is azt
    # mondanank, hogy „nincs cargo".
    cargo = shutil.which("cargo")
    if not cargo:
        for c in (Path.home() / ".cargo" / "bin" / "cargo.exe",
                  Path.home() / ".cargo" / "bin" / "cargo"):
            if c.exists():
                cargo = str(c)
                break
    if not cargo:
        print("A `cargo` nem talalhato — a nativ mag NEM epul fel.")
        print()
        print("Ez NEM hiba: a program Python-uton fut tovabb, ugyanazzal az")
        print("eredmennyel, csak lassabban. Ha akarod a gyorsitast:")
        print("  1. https://rustup.rs  (Windowson a GNU-toolchain is jo:")
        print("     rustup-init.exe --default-host x86_64-pc-windows-gnu)")
        print("  2. python tools/build_native.py")
        return 0
    if not (CRATE / "Cargo.toml").exists():
        print(f"Nincs crate: {CRATE}")
        return 1
    print(f"Forditas: {CRATE}")
    r = subprocess.run([cargo, "build", "--release"], cwd=str(CRATE))
    if r.returncode != 0:
        print("A forditas NEM sikerult.")
        return r.returncode
    from core import native
    native._probalt = False               # a betoltest ujra megprobaljuk
    p = native.library_path()
    print(f"Kesz: {p}")
    if native.available():
        print(f"Betoltve, ABI {native.EXPECTED_ABI} — a nativ mag EL.")
    else:
        print(f"⚠ Nem hasznalhato: {native.status()}")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    sys.exit(main())
