"""Encodes AV2 test streams with AVM and writes the reference MD5 of each one.

For every input .y4m and QP: optionally converts it to 8 bit with ffmpeg, encodes the first N frames with avmenc
using the random-access settings of Scripts-ViTech (AVM/cfg/av2/random_access.cfg), then decodes the stream with
avmdec (the reference decoder) to write <stream>.md5, which bench.py uses to check every decode on the phone.
With the optimized build, --threads sets the encoder threads; the generic build only runs single-threaded.

Interactive: python3 scripts/make_streams.py
It asks for the sources (.y4m under reference_videos/), the bit depths, the QPs, the number of frames, the speed
preset, the encoder threads and the output folder. The smallest sources are encoded first.

Stream names follow <video>_<height>p_<bits>bit_qp<QP>_f<frames>_s<preset>.obu; the encoder log is kept as .enc.log.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

from interativo import ask_number, ask_numbers, ask_text, confirm_or_exit, menu, pick_files, title

HERE = Path(__file__).resolve().parent.parent
# build/avm-x86: optimized (AVM_TARGET_CPU=x86_64) and multithreaded. build/avm: generic C, single-threaded;
# the av2-normative branch builds generic unless AVM_TARGET_CPU is set, which makes it many times slower.
AVM_DIR = next(d for d in (HERE / "build/avm-x86", HERE / "build/avm") if (d / "avmenc").exists())
AVMENC = AVM_DIR / "avmenc"
AVMDEC = AVM_DIR / "avmdec"
RA_CFG = HERE.parent / "Scripts-ViTech/AVM/cfg/av2/random_access.cfg"


def y4m_height(path):
    """Frame height from the Y4M header (the 'H' field)."""
    with open(path, "rb") as f:
        header = f.readline().decode()
    return next(int(t[1:]) for t in header.split() if t.startswith("H"))


def to_8bit(src, dst):
    """Converts a 10-bit .y4m to 8 bit with ffmpeg, once; later calls reuse the file."""
    if not dst.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-pix_fmt", "yuv420p",
                        "-strict", "-1", str(dst)], check=True)
    return dst


def main():
    os.chdir(HERE)
    if not RA_CFG.exists():
        sys.exit(f"{RA_CFG} não existe (vem do repositório Scripts-ViTech, ao lado do AV2-Android).")
    inputs = sorted(pick_files("FONTES (.y4m)", HERE / "reference_videos", {".y4m"}), key=lambda p: p.stat().st_size)
    depths = [[10], [8], [10, 8]][menu("BIT DEPTH", ["10 bits", "8 bits (converte a fonte com ffmpeg)", "10 e 8 bits"],
                                       "Selecione (em branco = 1): ", default=0)]
    title("CODIFICAÇÃO")
    qps = ask_numbers("QPs (qindex do AVM)", [160])
    frames = ask_number("Frames", 33, minimum=1)
    cpu_used = ask_number("--cpu-used (0 = o da CTC, mais lento; maior = mais rápido)", 0, minimum=0)
    threads = ask_number("Threads do encoder", 8, minimum=1) if AVM_DIR.name == "avm-x86" else 1
    out = Path(ask_text("Pasta de saída", "streams"))
    print(f"\n{len(inputs) * len(depths) * len(qps)} stream(s) com {AVMENC}")
    confirm_or_exit()

    out.mkdir(parents=True, exist_ok=True)
    ra_args = [a for line in RA_CFG.read_text().splitlines() for a in line.split("#", 1)[0].split()
               if not a.startswith("--cpu-used")]

    for src in inputs:
        for depth in depths:
            source = src if depth == 10 else to_8bit(src, out / f"{src.stem}_8bit.y4m")
            for qp in qps:
                name = f"{src.stem.split('_')[0]}_{y4m_height(src)}p_{depth}bit_qp{qp}_f{frames}_s{cpu_used}"
                obu = out / f"{name}.obu"
                cmd = [str(AVMENC), *ra_args, f"--cpu-used={cpu_used}", f"--bit-depth={depth}",
                       *([f"--threads={threads}"] if AVM_DIR.name == "avm-x86" else []),
                       f"--input-bit-depth={depth}", f"--qp={qp}", f"--limit={frames}",
                       "-o", str(obu), str(source)]
                t0 = time.time()
                log = out / f"{name}.enc.log"
                with open(log, "w") as f:
                    subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True)
                md5 = subprocess.run([str(AVMDEC), "--md5", "--rawvideo", str(obu)],
                                     capture_output=True, text=True, check=True).stdout.split()[0]
                (out / f"{name}.md5").write_text(md5 + "\n")
                print(f"{obu.name}: {obu.stat().st_size / 1024:.0f} KiB, encoded in {time.time() - t0:.0f} s, md5 {md5}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
