"""Encodes AV1 test streams with libaom or SVT-AV1 (through ffmpeg) and writes the reference MD5 of each one.

The AV1 counterpart of make_streams.py, for the AV1 vs. AV2 comparison. For every input .y4m and QP: optionally
converts it to 8 bit with ffmpeg (the same file make_streams.py uses), encodes the first N frames at a fixed QP with a
GOP close to the AVM random-access settings (16-frame mini-GOP, key frame every 65 frames, no TPL, no adaptive
quantization), then decodes the stream to write <stream>.md5 in the form dav1d's md5 muxer prints, which bench.py
checks on the phone. Optionally it also measures the decoded stream against its source and appends a row to
<out>/quality.csv.

Interactive: python3 scripts/make_av1_streams.py
It asks for the sources (.y4m under reference_videos/), the encoder, the bit depths, the QPs, the number of frames,
the speed preset, the threads, whether to measure PSNR and the output folder. The smallest sources are encoded first.

Stream names follow <video>_<height>p_<bits>bit_<encoder>_q<QP>_f<frames>_p<preset>.ivf; the encoder log is kept as
.enc.log.
"""

import csv
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from interativo import ask_number, ask_numbers, ask_text, ask_yes, confirm_or_exit, menu, pick_files, title

HERE = Path(__file__).resolve().parent.parent
DAV1D = HERE / "build/dav1d-x86/tools/dav1d"
GOP = 65       # --kf-min-dist / --kf-max-dist in Scripts-ViTech/AVM/cfg/av2/random_access.cfg
MINI_GOP = 16  # --min-gf-interval / --max-gf-interval
LAG = 19       # --lag-in-frames


def y4m_header(path):
    """Height and frame rate from the Y4M header (the 'H' and 'F' fields)."""
    with open(path, "rb") as f:
        fields = {t[0]: t[1:] for t in f.readline().decode().split()[1:]}
    num, den = fields["F"].split(":")
    return int(fields["H"]), int(num) / int(den)


def to_8bit(src, dst):
    """Converts a 10-bit .y4m to 8 bit with ffmpeg, once; later calls reuse the file."""
    if not dst.exists():
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-pix_fmt", "yuv420p",
                        "-strict", "-1", str(dst)], check=True)
    return dst


def encoder_args(encoder, qp, preset, threads):
    """ffmpeg arguments for a fixed-QP random-access encode."""
    if encoder == "libaom":
        # Constant-quality mode (end-usage=q, as in the AVM config). libaom 3.8 has no use-fixed-qp-offsets option
        # through ffmpeg, so the QP offsets of the pyramid levels are libaom's defaults.
        return ["-c:v", "libaom-av1", "-cpu-used", str(preset), "-crf", str(qp), "-b:v", "0",
                "-g", str(GOP), "-keyint_min", str(GOP), "-lag-in-frames", str(LAG), "-aq-mode", "0",
                "-threads", str(threads), "-row-mt", "1",
                "-aom-params", f"min-gf-interval={MINI_GOP}:max-gf-interval={MINI_GOP}:gf-min-pyr-height=4:"
                               "gf-max-pyr-height=4:deltaq-mode=0:enable-tpl-model=0:enable-keyframe-filtering=0"]
    # SVT-AV1: -qp with aq-mode=0 is CQP (fixed QP per pyramid level); hierarchical-levels=4 is a 16-frame mini-GOP.
    return ["-c:v", "libsvtav1", "-preset", str(preset), "-qp", str(qp), "-g", str(GOP),
            "-svtav1-params", f"hierarchical-levels=4:aq-mode=0:lp={threads}"]


def stream_md5(ivf, depth):
    """MD5 of the decoded frames, as dav1d --verify computes it. Uses the host dav1d when built, else ffmpeg, which
    hashes the same bytes (planes in order, 16-bit little endian above 8 bit)."""
    if DAV1D.exists():
        out = subprocess.run([str(DAV1D), "-q", "-i", str(ivf), "--muxer", "md5", "-o", "/dev/stdout"],
                             capture_output=True, text=True, check=True).stdout
        return out.split()[0]
    pix_fmt = "yuv420p" if depth == 8 else "yuv420p10le"
    out = subprocess.run(["ffmpeg", "-v", "error", "-c:v", "libdav1d", "-i", str(ivf), "-f", "md5",
                          "-pix_fmt", pix_fmt, "-"], capture_output=True, text=True, check=True).stdout
    return out.strip().removeprefix("MD5=")


def psnr(ivf, source, frames):
    """Average PSNR (Y, and the weighted YUV average) of the decoded stream against the first frames of its source."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(ivf), "-i", str(source), "-frames:v", str(frames),
                          "-lavfi", "[0:v][1:v]psnr=shortest=1", "-f", "null", "-"],
                         capture_output=True, text=True, check=True).stderr
    m = re.search(r"PSNR y:([\d.inf]+) .* average:([\d.inf]+)", err)
    return float(m.group(1)), float(m.group(2))


def main():
    os.chdir(HERE)
    inputs = sorted(pick_files("FONTES (.y4m)", HERE / "reference_videos", {".y4m"}), key=lambda p: p.stat().st_size)
    encoder = ["svtav1", "libaom"][menu("ENCODER (pelo ffmpeg)", ["SVT-AV1", "libaom"], "Selecione (em branco = 1): ",
                                        default=0)]
    depths = [[10], [8], [10, 8]][menu("BIT DEPTH", ["10 bits", "8 bits (converte a fonte com ffmpeg)", "10 e 8 bits"],
                                       "Selecione (em branco = 1): ", default=0)]
    title("CODIFICAÇÃO")
    qps = ask_numbers("QPs do AV1, 0-63 (maior = menos bitrate)", [40])
    frames = ask_number("Frames", 33, minimum=1)
    preset = ask_number("Preset (libaom cpu-used 0-8, SVT-AV1 0-13; maior = mais rápido)",
                        0 if encoder == "libaom" else 2, minimum=0)
    threads = ask_number("Threads do encoder", 8, minimum=1)
    with_psnr = ask_yes("Medir o PSNR de cada stream (grava <saída>/quality.csv)? [s/N]: ")
    out = Path(ask_text("Pasta de saída", "streams"))
    print(f"\n{len(inputs) * len(depths) * len(qps)} stream(s) com {encoder}")
    confirm_or_exit()

    out.mkdir(parents=True, exist_ok=True)
    quality = out / "quality.csv"
    for src in inputs:
        for depth in depths:
            source = src if depth == 10 else to_8bit(src, out / f"{src.stem}_8bit.y4m")
            height, fps = y4m_header(src)
            for qp in qps:
                name = f"{src.stem.split('_')[0]}_{height}p_{depth}bit_{encoder}_q{qp}_f{frames}_p{preset}"
                ivf = out / f"{name}.ivf"
                cmd = ["ffmpeg", "-y", "-i", str(source), "-frames:v", str(frames),
                       *encoder_args(encoder, qp, preset, threads),
                       "-pix_fmt", "yuv420p" if depth == 8 else "yuv420p10le", str(ivf)]
                t0 = time.time()
                log = out / f"{name}.enc.log"
                with open(log, "w") as f:
                    f.write(" ".join(cmd) + "\n\n")  # the ffmpeg banner and encoder version follow
                    f.flush()
                    subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True, env={**os.environ, "SVT_LOG": "3"})
                elapsed = time.time() - t0
                md5 = stream_md5(ivf, depth)
                (out / f"{name}.md5").write_text(md5 + "\n")
                kbps = ivf.stat().st_size * 8 / 1000 / (frames / fps)
                line = f"{ivf.name}: {ivf.stat().st_size / 1024:.0f} KiB, {kbps:.0f} kbps, encoded in {elapsed:.0f} s, md5 {md5}"
                if with_psnr:
                    psnr_y, psnr_yuv = psnr(ivf, source, frames)
                    new = not quality.exists()
                    with open(quality, "a", newline="") as f:
                        w = csv.writer(f)
                        if new:
                            w.writerow(["stream", "encoder", "qp", "bitdepth", "frames", "kbps", "psnr_y", "psnr_yuv"])
                        w.writerow([ivf.name, encoder, qp, depth, frames, round(kbps, 1), psnr_y, psnr_yuv])
                    line += f", PSNR Y {psnr_y:.2f} dB, YUV {psnr_yuv:.2f} dB"
                print(line)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nCancelado.")
