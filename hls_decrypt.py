import os, struct
from pathlib import Path

seg_dir  = "/tmp/hls_segs"
method   = open("/tmp/hls_method.txt").read().strip() if os.path.exists("/tmp/hls_method.txt") else "NONE"
key_path = "/tmp/hls.key"
segs     = sorted(Path(seg_dir).glob("seg_*.ts"))
print(f"🧩 {len(segs)} segments | encryption={method}")

with open("source.ts", "wb") as out:
    if method == "AES-128" and os.path.exists(key_path):
        try:
            from Cryptodome.Cipher import AES
        except ImportError:
            from Crypto.Cipher import AES
        key    = open(key_path, "rb").read()
        iv_fix = open("/tmp/hls_iv.bin", "rb").read() if os.path.exists("/tmp/hls_iv.bin") else None
        for i, seg in enumerate(segs):
            data = seg.read_bytes()
            iv   = iv_fix if iv_fix else struct.pack(">I", i).rjust(16, b"\x00")
            dec  = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
            pad  = dec[-1]
            out.write(dec[:-pad] if 1 <= pad <= 16 else dec)
        print("✅ Decrypted and merged → source.ts")
    else:
        for seg in segs:
            out.write(seg.read_bytes())
        print("✅ Merged → source.ts (no encryption)")
