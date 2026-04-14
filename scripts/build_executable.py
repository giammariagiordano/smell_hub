#!/usr/bin/env python3
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = PROJECT_ROOT / "launcher.py"


def add_data_arg(src: Path, dst: str) -> str:
    sep = ";" if platform.system().lower().startswith("win") else ":"
    return f"{src}{sep}{dst}"


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except Exception as e:
        raise SystemExit(
            "PyInstaller non trovato. Installa con: pip install pyinstaller\n"
            f"Dettaglio: {e}"
        )


def build(onefile: bool, clean: bool) -> int:
    ensure_pyinstaller()

    if not ENTRYPOINT.exists():
        raise SystemExit(f"Entrypoint non trovato: {ENTRYPOINT}")

    if clean:
        for d in (PROJECT_ROOT / "build", PROJECT_ROOT / "dist"):
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--name",
        "SmellHub",
        "--console",
        "--paths",
        str(PROJECT_ROOT),
    ]

    cmd.append("--onefile" if onefile else "--onedir")

    for src, dst in [
        (PROJECT_ROOT / "api", "api"),
        (PROJECT_ROOT / "analyzers", "analyzers"),
        (PROJECT_ROOT / "core", "core"),
        (PROJECT_ROOT / "models", "models"),
        (PROJECT_ROOT / "utils", "utils"),
        (PROJECT_ROOT / "web", "web"),
        (PROJECT_ROOT / "smell_ai", "smell_ai"),
        (PROJECT_ROOT / "SE_Emotion_PTM-3589", "SE_Emotion_PTM-3589"),
        (PROJECT_ROOT / "DPy", "DPy"),
        (PROJECT_ROOT / "requirements.txt", "requirements.txt"),
    ]:
        if src.exists():
            cmd.extend(["--add-data", add_data_arg(src, dst)])

    # Import dinamici usati dal sentiment analyzer e da uvicorn import string/app loader.
    cmd.extend(["--hidden-import", "api.main"])
    cmd.extend(["--hidden-import", "fastapi.middleware.cors"])
    cmd.extend(["--hidden-import", "fastapi.staticfiles"])
    cmd.extend(["--hidden-import", "fastapi.responses"])
    cmd.extend(["--hidden-import", "uvicorn"])
    cmd.extend(["--hidden-import", "torch"])
    cmd.extend(["--hidden-import", "transformers"])

    cmd.append(str(ENTRYPOINT))

    print("Running:")
    print(" ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), check=False)
    return int(proc.returncode)


def main() -> None:
    ap = argparse.ArgumentParser(description="Build executable SmellHub con PyInstaller")
    ap.add_argument("--onefile", action="store_true", help="Genera un singolo file eseguibile (piu lento all'avvio)")
    ap.add_argument("--no-clean", action="store_true", help="Non pulire build/ e dist/ prima del build")
    args = ap.parse_args()

    rc = build(onefile=bool(args.onefile), clean=not bool(args.no_clean))
    if rc != 0:
        raise SystemExit(rc)

    dist = PROJECT_ROOT / "dist"
    print(f"\nBuild completata. Output in: {dist}")
    if args.onefile:
        exe = "SmellHub.exe" if platform.system().lower().startswith("win") else "SmellHub"
        print(f"Eseguibile: {dist / exe}")
    else:
        app_dir = dist / "SmellHub"
        exe = "SmellHub.exe" if platform.system().lower().startswith("win") else "SmellHub"
        print(f"Cartella app: {app_dir}")
        print(f"Avvio: {app_dir / exe}")


if __name__ == "__main__":
    main()
