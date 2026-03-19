"""
hls_parse.py <manifest_file> <base_url> [referer]

Reads an already-downloaded m3u8 manifest, builds an aria2c input file.
Also saves: media sequence start, per-segment IVs if explicit.
All HTTP is handled by bash curl upstream — no network calls here.
"""
import sys, os, re

manifest_file = sys.argv[1]
base_url      = sys.argv[2]
referer       = sys.argv[3] if len(sys.argv) > 3 else ""
seg_dir       = "/tmp/hls_segs"
os.makedirs(seg_dir, exist_ok=True)

lines     = open(manifest_file).read().splitlines()
segs      = []
seg_ivs   = {}   # seg_index -> explicit IV hex string
seq_start = 0
current_iv = None

for line in lines:
    if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
        seq_start = int(line.split(":", 1)[1].strip())

    if line.startswith("#EXT-X-KEY"):
        iv_m = re.search(r'IV=0x([0-9a-fA-F]+)', line)
        current_iv = iv_m.group(1).zfill(32) if iv_m else None

    elif line and not line.startswith("#"):
        seg_url = line if line.startswith("http") else base_url + "/" + line
        idx = len(segs)
        segs.append(seg_url)
        # Save explicit IV for this segment index if present
        if current_iv:
            seg_ivs[idx] = current_iv

print(f"📋 {len(segs)} segments | seq_start={seq_start}")

# Save sequence start for IV calculation in bash
open("/tmp/hls_seq_start.txt", "w").write(str(seq_start))

# Save per-segment explicit IVs
for idx, iv in seg_ivs.items():
    open(f"/tmp/hls_iv_{idx}.hex", "w").write(iv)

# Write aria2c input file
with open("/tmp/hls_aria2.txt", "w") as f:
    for i, seg in enumerate(segs):
        f.write(f"{seg}\n  dir={seg_dir}\n  out=seg_{i:05d}.ts\n")
        f.write(f"  header=User-Agent: Mozilla/5.0\n")
        if referer:
            f.write(f"  header=Referer: {referer}\n")

open("/tmp/hls_segcount.txt", "w").write(str(len(segs)))
