"""Encodes AV2 test streams with AVM and writes the reference MD5 of each one.

For every input .y4m and QP: optionally converts it to 8 bit with ffmpeg, encodes the first N frames with avmenc
using the random-access settings of Scripts-ViTech (AVM/cfg/random_access.cfg), then decodes the stream with
avmdec (the reference decoder) to write <stream>.md5, which bench.py uses to check every decode on the phone.
With the optimized build, --threads sets the encoder threads; the generic build only runs single-threaded.

Usage (from the AV2-Android folder):
    python scripts/make_streams.py reference_videos/SparksElevator_480x270p_5994_10bit.y4m \
        --qp 210 --frames 17 --bitdepth 10 8 --cpu-used 9 --out streams/poc

Stream names follow <video>_<height>p_<bits>bit_qp<QP>_f<frames>_s<preset>.obu; the encoder log is kept as .enc.log.
"""

import argparse
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
# build/avm-x86: optimized (AVM_TARGET_CPU=x86_64) and multithreaded. build/avm: generic C, single-threaded;
# the av2-normative branch builds generic unless AVM_TARGET_CPU is set, which makes it many times slower.
AVM_DIR = next(d for d in (HERE / "build/avm-x86", HERE / "build/avm") if (d / "avmenc").exists())
AVMENC = AVM_DIR / "avmenc"
AVMDEC = AVM_DIR / "avmdec"
RA_CFG = HERE.parent / "Scripts-ViTech/AVM/cfg/random_access.cfg"


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
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", type=Path, help=".y4m sources")
    ap.add_argument("--qp", type=int, nargs="+", default=[160])
    ap.add_argument("--frames", type=int, default=33)
    ap.add_argument("--bitdepth", type=int, nargs="+", default=[10], choices=[8, 10])
    ap.add_argument("--cpu-used", type=int, default=0,
                    help="AVM speed preset; the CTC uses 0, higher is faster but uses fewer tools")
    ap.add_argument("--threads", type=int, default=8, help="encoder threads (optimized build only)")
    ap.add_argument("--out", type=Path, default=Path("streams"))
    opts = ap.parse_args()

    opts.out.mkdir(parents=True, exist_ok=True)
    ra_args = [a for a in RA_CFG.read_text().split() if not a.startswith("--cpu-used")]

    for src in opts.inputs:
        for depth in opts.bitdepth:
            source = src if depth == 10 else to_8bit(src, opts.out / f"{src.stem}_8bit.y4m")
            for qp in opts.qp:
                name = f"{src.stem.split('_')[0]}_{y4m_height(src)}p_{depth}bit_qp{qp}_f{opts.frames}_s{opts.cpu_used}"
                obu = opts.out / f"{name}.obu"
                cmd = [str(AVMENC), *ra_args, f"--cpu-used={opts.cpu_used}", f"--bit-depth={depth}",
                       *([f"--threads={opts.threads}"] if AVM_DIR.name == "avm-x86" else []),
                       f"--input-bit-depth={depth}", f"--qp={qp}", f"--limit={opts.frames}",
                       "-o", str(obu), str(source)]
                t0 = time.time()
                log = opts.out / f"{name}.enc.log"
                with open(log, "w") as f:
                    subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=True)
                md5 = subprocess.run([str(AVMDEC), "--md5", "--rawvideo", str(obu)],
                                     capture_output=True, text=True, check=True).stdout.split()[0]
                (opts.out / f"{name}.md5").write_text(md5 + "\n")
                print(f"{obu.name}: {obu.stat().st_size / 1024:.0f} KiB, encoded in {time.time() - t0:.0f} s, md5 {md5}")


if __name__ == "__main__":
    main()
