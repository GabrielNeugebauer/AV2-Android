"""Installs the decoders on a phone (install_phone.py), checks every test-stream decode against its reference MD5 and
runs checkasm.
  dav2d: the dav2d-test-data streams (AVM v15 conformance), then checkasm.
  dav1d: checkasm-dav1d, then the AV1 streams of a folder under streams/ that have a .md5, if any.

Interactive: python3 scripts/phone_smoke_test.py
"""
import re
import subprocess
import sys

from interativo import ROOT, adb_shell, choose_phone, confirm_or_exit, menu, title
from install_phone import PHONE_DIR, choose_install, install


def verify(serial, dec, streams, extra=""):
    """Decodes each (local file, md5) on the phone with --verify. Returns (passed, failed)."""
    passed = failed = 0
    for local, md5 in streams:
        subprocess.run(["adb", "-s", serial, "push", str(local), f"{PHONE_DIR}/streams/"], check=True,
                       capture_output=True)
        rc, _ = adb_shell(serial, f"{PHONE_DIR}/{dec} -q --threads 1 {extra} -i {PHONE_DIR}/streams/{local.name} "
                                  f"--verify {md5}")
        print(f"{'PASS' if rc == 0 else 'FAIL'} {local.name}")
        passed, failed = passed + (rc == 0), failed + (rc != 0)
    print(f"Streams: {passed} passaram, {failed} falharam")
    return passed, failed


def checkasm(serial, name):
    rc, _ = adb_shell(serial, f"test -x {PHONE_DIR}/{name}")
    if rc != 0:
        print(f"{name} não está no celular (o build_*.sh o compila)")
        return
    out = adb_shell(serial, f"{PHONE_DIR}/{name} 2>&1")[1].splitlines()
    print(f"{name}: {out[-1] if out else 'sem saída'}")


def main():
    serial = choose_phone()
    arch, decoders = choose_install(serial)
    av1_dir = None
    if "dav1d" in decoders:
        folders = sorted({p.parent for p in (ROOT / "streams").rglob("*.ivf") if p.with_suffix(".md5").exists()})
        if folders:
            rows = ["nenhuma (só o checkasm)"] + [str(f.relative_to(ROOT)) for f in folders]
            sel = menu("STREAMS AV1 (dav1d)", rows, "Selecione a pasta (em branco = 1): ", default=0)
            av1_dir = folders[sel - 1] if sel else None
        else:
            print("\nNenhum stream AV1 (.ivf com .md5) em streams/: o dav1d terá só o checkasm.")
    confirm_or_exit()

    installed = install(serial, arch, decoders)
    if "dav2d" in installed:
        title("dav2d")
        data = ROOT / "src/dav2d-test-data/avm"
        expected = re.findall(r"files\('([^']+)'\),\s*'([0-9a-f]{32})'", (data / "meson.build").read_text())
        verify(serial, "dav2d", [(data / name, md5) for name, md5 in expected], "--filmgrain=1")
        checkasm(serial, "checkasm")
    if "dav1d" in installed:
        title("dav1d")
        checkasm(serial, "checkasm-dav1d")
        if av1_dir:
            streams = sorted(av1_dir.glob("*.ivf"))
            verify(serial, "dav1d", [(s, s.with_suffix(".md5").read_text().split()[0]) for s in streams
                                     if s.with_suffix(".md5").exists()])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
