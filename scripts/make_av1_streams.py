"""Encodes AV1 test streams with libaom or SVT-AV1 (through ffmpeg) and writes the reference MD5 of each one.

The AV1 counterpart of make_streams.py, for the AV1 vs. AV2 comparison. For every input .y4m and QP: optionally
converts it to 8 bit with ffmpeg (the same file make_streams.py uses), encodes the first N frames at a fixed QP with a
GOP close to the AVM random-access settings (16-frame mini-GOP, key frame every 65 frames, no TPL, no adaptive
quantization), then decodes the stream to write <stream>.md5 in the form dav1d's md5 muxer prints, which bench.py
checks on the phone. With --psnr it also measures the decoded stream against its source and appends a row to
<out>/quality.csv.

Usage (from the AV2-Android folder):
    python scripts/make_av1_streams.py reference_videos/SparksElevator_480x270p_5994_10bit.y4m \
        --encoder svtav1 --qp 40 --frames 17 --bitdepth 10 8 --preset 8 --out streams/poc_av1 --psnr

Stream names follow <video>_<height>p_<bits>bit_<encoder>_q<QP>_f<frames>_p<preset>.ivf; the encoder log is kept as
.enc.log.
"""

import argparse
import csv
import os
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
DAV1D = HERE / "build/dav1d-x86/tools/dav1d"
GOP = 65       # --kf-min-dist / --kf-max-dist in Scripts-ViTech/AVM/cfg/random_access.cfg
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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path, help=".y4m sources")
    ap.add_argument("--encoder", choices=["libaom", "svtav1"], default="svtav1")
    ap.add_argument("--qp", type=int, nargs="+", default=[40], help="AV1 QP, 0-63 (higher = lower bitrate)")
    ap.add_argument("--frames", type=int, default=33)
    ap.add_argument("--bitdepth", type=int, nargs="+", default=[10], choices=[8, 10])
    ap.add_argument("--preset", type=int, default=None,
                    help="speed preset: libaom cpu-used 0-8 (default 0), SVT-AV1 preset 0-13 (default 2)")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--psnr", action="store_true", help="append PSNR of each stream to <out>/quality.csv")
    ap.add_argument("--out", type=Path, default=Path("streams"))
    opts = ap.parse_args()
    preset = opts.preset if opts.preset is not None else 0 if opts.encoder == "libaom" else 2

    opts.out.mkdir(parents=True, exist_ok=True)
    quality = opts.out / "quality.csv"
    for src in opts.inputs:
        for depth in opts.bitdepth:
            source = src if depth == 10 else to_8bit(src, opts.out / f"{src.stem}_8bit.y4m")
            height, fps = y4m_header(src)
            for qp in opts.qp:
                name = f"{src.stem.split('_')[0]}_{height}p_{depth}bit_{opts.encoder}_q{qp}_f{opts.frames}_p{preset}"
                ivf = opts.out / f"{name}.ivf"
                cmd = ["ffmpeg", "-y", "-i", str(source), "-frames:v", str(opts.frames),
                       *encoder_args(opts.encoder, qp, preset, opts.threads),
                       "-pix_fmt", "yuv420p" if depth == 8 else "yuv420p10le", str(ivf)]
                t0 = time.time()
                log = opts.out / f"{name}.enc.log"
                with open(log, "w") as f:
                    f.write(" ".join(cmd) + "\n\n")  # the ffmpeg banner and encoder version follow
                    f.flush()
                    subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True, env={**os.environ, "SVT_LOG": "3"})
                elapsed = time.time() - t0
                md5 = stream_md5(ivf, depth)
                (opts.out / f"{name}.md5").write_text(md5 + "\n")
                kbps = ivf.stat().st_size * 8 / 1000 / (opts.frames / fps)
                line = f"{ivf.name}: {ivf.stat().st_size / 1024:.0f} KiB, {kbps:.0f} kbps, encoded in {elapsed:.0f} s, md5 {md5}"
                if opts.psnr:
                    psnr_y, psnr_yuv = psnr(ivf, source, opts.frames)
                    new = not quality.exists()
                    with open(quality, "a", newline="") as f:
                        w = csv.writer(f)
                        if new:
                            w.writerow(["stream", "encoder", "qp", "bitdepth", "frames", "kbps", "psnr_y", "psnr_yuv"])
                        w.writerow([ivf.name, opts.encoder, qp, depth, opts.frames, round(kbps, 1), psnr_y, psnr_yuv])
                    line += f", PSNR Y {psnr_y:.2f} dB, YUV {psnr_yuv:.2f} dB"
                print(line)


if __name__ == "__main__":
    main()
