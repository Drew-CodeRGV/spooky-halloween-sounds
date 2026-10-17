"""Run every test in this folder. No framework: each file asserts and prints what it checked.

    python3 tests/run.py          # all of them
    python3 tests/run.py track    # just the ones whose name contains "track"
"""
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
pick = sys.argv[1] if len(sys.argv) > 1 else ""
files = sorted(f for f in HERE.glob("test_*.py") if pick in f.stem)
if not files:
    sys.exit(f"no tests matching {pick!r}")

failed = []
for f in files:
    r = subprocess.run([sys.executable, str(f)], capture_output=True, text=True)
    ok = r.returncode == 0
    print(f"{'PASS' if ok else 'FAIL'}  {f.name}")
    if not ok:
        failed.append(f.name)
        print((r.stdout + r.stderr).rstrip() + "\n")

print(f"\n{len(files) - len(failed)}/{len(files)} passed")
sys.exit(1 if failed else 0)
