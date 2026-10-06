#!/usr/bin/env python3
"""Build deterministic source archives and checksums for review, never publish."""
from pathlib import Path
import hashlib
import subprocess
import tarfile
import zipfile
import io
import gzip
import os
from release_files import release_files

root=Path(__file__).resolve().parents[1]
subprocess.run([os.sys.executable,str(root/"scripts/validate_release.py")],check=True)
out=root/"releases";out.mkdir(exist_ok=True)
files=release_files(root)
prefix="parallax-1.0.0"
with zipfile.ZipFile(out/(prefix+".zip"),"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for path in files:
        info=zipfile.ZipInfo(prefix+"/"+str(path.relative_to(root)),date_time=(2026,10,6,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
        info.external_attr=(path.stat().st_mode&0o777|0o100000)<<16
        archive.writestr(info,path.read_bytes())
with (out/(prefix+".tar.gz")).open("wb") as destination, gzip.GzipFile(filename="",mode="wb",fileobj=destination,mtime=1791244800) as compressed, tarfile.open(fileobj=compressed,mode="w") as archive:
    for path in files:
        info=tarfile.TarInfo(prefix+"/"+str(path.relative_to(root)));data=path.read_bytes()
        info.size=len(data);info.mode=path.stat().st_mode&0o777;info.mtime=1791244800
        archive.addfile(info,io.BytesIO(data))
subprocess.run(["uv","build","--out-dir",str(out)],cwd=root,check=True,env={**os.environ,"SOURCE_DATE_EPOCH":"1791244800"})
artifacts=sorted(p for p in out.iterdir() if p.name.startswith((prefix,"parallax_team-1.0.0")) and (p.suffix in {".zip",".whl"} or p.name.endswith(".tar.gz")))
(out/"SHA256SUMS").write_text("".join(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+p.name+"\n" for p in artifacts))
print(f"Prepared {len(artifacts)} release archives and SHA256SUMS in {out}")
