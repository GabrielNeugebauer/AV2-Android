"""Frequency sweep: runs bench.py once per available frequency of one CPU cluster, with the decoder kept on that
cluster's cores, on battery. Shows how decoding speed and energy scale with clock speed on one core type.

Interactive: python3 scripts/freq_sweep.py   (needs root on the phone: it pins frequencies and pauses USB charging)
On the Redmi, policy0 is the six A55 cores 0-5 and policy6 the two A76 cores 6-7.
"""
import os
import signal
import sys
from pathlib import Path
from types import SimpleNamespace

from bench import choose_decoder_and_streams, cores_label, describe, read_policies, run
from interativo import (ROOT, ask_number, ask_numbers, ask_text, choose_phone, confirm_or_exit, has_root, menu,
                        title)


def main():
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(1))
    os.chdir(ROOT)
    serial = choose_phone()
    if not has_root(serial):
        sys.exit("A varredura precisa de root no celular (fixa a frequência e pausa a carga pela USB).")
    decoder, streams = choose_decoder_and_streams(serial)
    policies = {p: v for p, v in read_policies(serial).items() if v[1]}
    if not policies:
        sys.exit("As frequências da CPU não são legíveis neste celular.")
    plist = list(policies)
    policy = plist[menu("CLUSTER", [f"policy{p}: núcleos {cores_label(c)}, {len(f)} frequências"
                                    for p, (c, f) in policies.items()], "Selecione: ")]
    cpus, steps = policies[policy]
    picked = menu(f"FREQUÊNCIAS DA policy{policy}", [f"{f / 1000:.0f} MHz ({f} kHz)" for f in steps],
                  "Selecione (em branco = todas): ", multi=True, default=list(range(len(steps))))
    title("EXECUÇÃO")
    threads = ask_numbers("Threads do decodificador", [1])
    runs = ask_number("Execuções por stream e número de threads", 5, minimum=1)
    cooldown = ask_number("Esfriar até quantos °C antes de cada execução", 58.0, float)
    out = Path(ask_text("Arquivo CSV de saída", f"results/sweep_policy{policy}.csv"))

    base = dict(serial=serial, decoder=decoder, streams=streams, runs=runs, threads=threads, cpumask=None,
                lock_clocks=True, battery_power=True, cpus=cpus, cooldown_c=cooldown, cooldown_timeout=30.0,
                pause=0.0, out=out)
    describe(SimpleNamespace(**base, freqs={policy: steps[picked[0]]}))
    print(f"{len(picked)} frequência(s): {', '.join(str(steps[i]) for i in picked)} kHz")
    confirm_or_exit()
    for i in picked:
        title(f"policy{policy} a {steps[i]} kHz, núcleos {cores_label(cpus)}")
        run(SimpleNamespace(**base, freqs={policy: steps[i]}))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
