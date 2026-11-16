"""Pushes the decoders (dav2d, dav1d) and their checkasm builds to a phone, in /data/local/tmp/av2, and records the
source commit of each one in /data/local/tmp/av2/VERSIONS.

Interactive: python3 scripts/install_phone.py
It asks for the phone, the architecture (detected from the phone's ABI list) and the decoders. Each pushed file is
checked by SHA-256 on the phone. VERSIONS has one line per decoder (name, commit, arch, date); lines of decoders not
installed in the run are kept.
"""
import datetime
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

from interativo import ROOT, adb_shell, ask_yes, choose_phone, menu, phone_arch, title, confirm_or_exit

PHONE_DIR = "/data/local/tmp/av2"
DECODERS = {"dav2d": "checkasm", "dav1d": "checkasm-dav1d"}  # dav2d's checkasm keeps the plain name
ARCHES = ["arm64", "armv7"]


def build_paths(dec, arch):
    binary = ROOT / f"build/{dec}-{arch}/tools/{dec}"
    checkasm = ROOT / f"build/{dec}-{arch}-checkasm/tests/checkasm"
    return (binary if binary.is_file() else None), (checkasm if checkasm.is_file() else None)


def source_commit(dec):
    src = ROOT / "src" / dec
    try:
        commit = subprocess.run(["git", "-C", src, "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                                check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    dirty = subprocess.run(["git", "-C", src, "status", "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True).stdout.strip()
    return commit + ("-dirty" if dirty else "")


def push(serial, local, remote):
    subprocess.run(["adb", "-s", serial, "push", str(local), remote], check=True, capture_output=True)
    adb_shell(serial, f"chmod 755 {remote}", check=True)
    remote_hash = adb_shell(serial, f"sha256sum {remote}", check=True)[1].split()[0]
    if remote_hash != hashlib.sha256(Path(local).read_bytes()).hexdigest():
        raise RuntimeError(f"{remote}: o SHA-256 no celular difere do arquivo local")


def install(serial, arch, decoders, with_checkasm=True):
    """Installs the built decoders among `decoders`; returns the ones installed."""
    adb_shell(serial, f"mkdir -p {PHONE_DIR}/streams", check=True)
    installed = []
    for dec in decoders:
        binary, checkasm = build_paths(dec, arch)
        if binary is None:
            print(f"Pulando {dec}: build/{dec}-{arch}/tools/{dec} não está compilado (scripts/build_{dec}.sh)")
            continue
        print(f"[ Enviando ] {binary.relative_to(ROOT)} -> {PHONE_DIR}/{dec}")
        push(serial, binary, f"{PHONE_DIR}/{dec}")
        if with_checkasm:
            if checkasm:
                print(f"[ Enviando ] {checkasm.relative_to(ROOT)} -> {PHONE_DIR}/{DECODERS[dec]}")
                push(serial, checkasm, f"{PHONE_DIR}/{DECODERS[dec]}")
            else:
                print(f"Sem checkasm do {dec} para {arch} (scripts/build_{dec}.sh o compila)")
        installed.append(dec)

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    old = adb_shell(serial, f"cat {PHONE_DIR}/VERSIONS 2>/dev/null")[1].splitlines()
    lines = [l for l in old if l.strip() and l.split()[0] not in installed]
    lines += [f"{dec} {source_commit(dec)} {arch} {now}" for dec in installed]
    with tempfile.NamedTemporaryFile("w", suffix=".txt") as tmp:
        tmp.write("\n".join(sorted(lines)) + "\n")
        tmp.flush()
        subprocess.run(["adb", "-s", serial, "push", tmp.name, f"{PHONE_DIR}/VERSIONS"], check=True,
                       capture_output=True)
    return installed


def choose_install(serial):
    """Asks for the architecture and the decoders. Returns (arch, decoders)."""
    detected = ARCHES.index(phone_arch(serial))
    arch = ARCHES[menu("ARQUITETURA", [a + ("   (detectada)" if i == detected else "") for i, a in enumerate(ARCHES)],
                       f"Selecione a arquitetura (em branco = {ARCHES[detected]}): ", default=detected)]
    rows, built = [], []
    for i, dec in enumerate(DECODERS):
        binary, checkasm = build_paths(dec, arch)
        if binary:
            built.append(i)
            rows.append(f"{dec:6} commit {source_commit(dec)}" + ("" if checkasm else ", sem checkasm"))
        else:
            rows.append(f"{dec:6} não compilado (scripts/build_{dec}.sh)")
    if not built:
        sys.exit(f"Nenhum decodificador compilado para {arch}: rode scripts/build_dav2d.sh e build_dav1d.sh.")
    picked = menu("DECODIFICADORES", rows, "Selecione (em branco = todos os compilados): ", multi=True, default=built)
    return arch, [list(DECODERS)[i] for i in picked]


def main():
    serial = choose_phone()
    arch, decoders = choose_install(serial)
    with_checkasm = ask_yes("\nInstalar também o checkasm? [S/n]: ", default=True)
    confirm_or_exit("Instalar? [s/N]: ")
    try:
        installed = install(serial, arch, decoders, with_checkasm)
    except (RuntimeError, subprocess.CalledProcessError) as e:
        sys.exit(f"Erro: {e}")
    title("NO CELULAR")
    for dec in installed:
        print(f"{dec}: {adb_shell(serial, f'{PHONE_DIR}/{dec} --version 2>&1')[1]}")
    print(f"\n{PHONE_DIR}/VERSIONS:\n{adb_shell(serial, f'cat {PHONE_DIR}/VERSIONS')[1]}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
