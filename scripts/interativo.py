"""Interactive prompts shared by the scripts (in Portuguese, the same pattern as Scripts-ViTech).

Numbered menus accept lists and ranges such as 1,2,3 or 1-3,5; a blank answer takes the default shown in the prompt.
"""
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the AV2-Android folder


def parse_selection(selection_str, max_val):
    """Parses a string like '1,2,3-5' into a sorted list of unique integers."""
    selected = set()
    for part in selection_str.split(','):
        part = part.strip()
        if not part:
            continue
        try:
            if '-' in part:
                start, end = map(int, part.split('-'))
                selected.update(i for i in range(start, end + 1) if 1 <= i <= max_val)
            elif 1 <= int(part) <= max_val:
                selected.add(int(part))
            else:
                print(f"Aviso: Valor fora do limite ignorado '{part}'")
        except ValueError:
            print(f"Aviso: Entrada inválida ignorada '{part}'")
    return sorted(selected)


def title(text):
    print("\n========================================")
    print(f"  {text}")
    print("========================================")


def menu(heading, options, prompt, multi=False, default=None):
    """Numbered menu. Returns a 0-based index (a list of them with multi=True); blank returns `default` if given."""
    title(heading)
    for idx, opt in enumerate(options, 1):
        print(f"[{idx}] {opt}")
    print("========================================")
    while True:
        answer = input(prompt).strip()
        if not answer and default is not None:
            return default
        if multi:
            sel = parse_selection(answer, len(options))
            if sel:
                return [i - 1 for i in sel]
        elif answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        print("Seleção inválida.")


def ask_yes(prompt, default=False):
    answer = input(prompt).strip().lower()
    return default if not answer else answer in ("s", "sim", "y", "yes")


def ask_number(prompt, default, kind=int, minimum=None):
    while True:
        answer = input(f"{prompt} (em branco = {default}): ").strip()
        if not answer:
            return default
        try:
            value = kind(answer)
            if minimum is None or value >= minimum:
                return value
        except ValueError:
            pass
        print("Valor inválido.")


def ask_numbers(prompt, default):
    """Comma-separated integers, e.g. '160,210'."""
    while True:
        answer = input(f"{prompt}, separados por vírgula (em branco = {','.join(map(str, default))}): ").strip()
        if not answer:
            return list(default)
        try:
            return [int(x) for x in answer.replace(' ', ',').split(',') if x]
        except ValueError:
            print("Valor inválido.")


def ask_text(prompt, default):
    return input(f"{prompt} (em branco = {default}): ").strip() or default


def confirm_or_exit(prompt="Iniciar? [s/N]: "):
    if not ask_yes(prompt):
        sys.exit(0)


def pick_files(heading, folder, suffixes, need_md5=False, default_all=False):
    """Menu of the files under `folder` (recursive) with one of `suffixes`; with need_md5, only those with a .md5."""
    folder = Path(folder)
    files = sorted(p for p in folder.rglob('*') if p.suffix in suffixes and p.is_file()
                   and (not need_md5 or p.with_suffix('.md5').exists()))
    if not files:
        extra = " com .md5 ao lado" if need_md5 else ""
        sys.exit(f"Nenhum arquivo {'/'.join(suffixes)}{extra} em {folder}/.")
    rows = [str(p.relative_to(folder)) for p in files]
    blank = "todos" if default_all else None
    prompt = "Selecione (ex: 1,2,3 ou 1-3,5" + (f"; em branco = {blank}" if blank else "") + "): "
    picked = menu(heading, rows, prompt, multi=True, default=list(range(len(files))) if default_all else None)
    return [files[i] for i in picked]


def adb_shell(serial, command, root=False, check=False, timeout=None):
    """Runs a shell command on the phone; returns (exit code, output). With root=True it runs through su."""
    cmd = f"su -c {shlex.quote(command)}" if root else command
    res = subprocess.run(["adb", "-s", serial, "shell", cmd], stdin=subprocess.DEVNULL, capture_output=True,
                         text=True, timeout=timeout)
    if check and res.returncode != 0:
        raise RuntimeError(f"adb: '{command}' falhou ({res.returncode}): {(res.stderr or res.stdout).strip()}")
    return res.returncode, res.stdout.replace('\r', '').strip()


def has_root(serial):
    try:
        return "uid=0" in adb_shell(serial, "id", root=True, timeout=20)[1]
    except subprocess.TimeoutExpired:
        return False


def choose_phone():
    """Menu of the phones in `adb devices`; prints the chosen one's model and returns its serial."""
    try:
        out = subprocess.run(["adb", "devices", "-l"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"Erro ao rodar 'adb devices': {e}")
    devices = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        if parts[1] != "device":
            print(f"Aviso: {parts[0]} está '{parts[1]}' (autorize a depuração USB no celular).")
            continue
        info = dict(p.split(':', 1) for p in parts[2:] if ':' in p)
        devices.append((parts[0], info.get("model", "?")))
    if not devices:
        sys.exit("Nenhum celular conectado. Conecte por USB com a depuração USB ativada.")
    serial, _ = devices[menu("CELULAR", [f"{m}  ({s})" for s, m in devices], "Selecione o celular (em branco = 1): ",
                             default=0)]
    prop = lambda p: adb_shell(serial, f"getprop {p}")[1]  # noqa: E731
    print(f"\n{prop('ro.product.manufacturer')} {prop('ro.product.model')}, Android {prop('ro.build.version.release')}, "
          f"SoC {prop('ro.soc.model') or '?'}, ABIs {prop('ro.product.cpu.abilist')}")
    return serial


def phone_arch(serial):
    return "arm64" if "arm64-v8a" in adb_shell(serial, "getprop ro.product.cpu.abilist")[1] else "armv7"
