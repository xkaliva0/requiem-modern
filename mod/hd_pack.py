"""HD texture payload for Requiem Modern.
  py hd_pack.py build HD_DIR OUT.bin     LZMA of: u32 count, then per texture u32 index, u32 size, decoded HD bytes
  py hd_pack.py append EXE PAYLOAD.bin   append payload + footer (b'RQHDPAK1', u64 payload size) to the built exe
The launcher (requiem_modern.set_hd) reads the payload from the end of its own exe and builds the archive."""
import lzma, os, struct, sys
MAGIC = b"RQHDPAK1"

def build(hd_dir, out):
    import hd_build
    hd_build.HD_DIR = hd_dir
    parts = [struct.pack("<2I", i, len(h)) + h for i, h, is_hd in hd_build.entries() if is_hd]
    data = struct.pack("<I", len(parts)) + b"".join(parts)
    open(out, "wb").write(lzma.compress(data, preset=6))
    print(len(parts), "textures,", len(data), "->", os.path.getsize(out), "bytes")

def append(exe, payload, magic=MAGIC):
    """Blocks stack from the end of the exe: [exe][textures][RQHDPAK1 n][menu masters][RQMNPAK1 n]."""
    p = open(payload, "rb").read(); magic = magic.encode() if isinstance(magic, str) else magic
    with open(exe, "ab") as f:
        f.write(p); f.write(magic + struct.pack("<Q", len(p)))
    print("appended", len(p), "bytes to", exe)

if __name__ == "__main__":
    {"build": build, "append": append}[sys.argv[1]](*sys.argv[2:])
