import argparse, json
from pathlib import Path

def replace_text(root: Path, old: str, new: str):
    for rel in ["Cargo.toml","flutter/windows/runner/Runner.rc","flutter/windows/runner/main.cpp"]:
        p=root/rel
        if p.exists():
            text=p.read_text(encoding="utf-8",errors="ignore")
            changed=text.replace(old,new)
            if changed!=text:
                p.write_text(changed,encoding="utf-8")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--rustdesk",required=True)
    p.add_argument("--server",default="")
    p.add_argument("--key",default="")
    p.add_argument("--api",default="")
    p.add_argument("--appname",default="RustDesk")
    p.add_argument("--filename",default="rustdesk")
    p.add_argument("--extras",default="{}")
    a=p.parse_args()
    root=Path(a.rustdesk)

    # The server/key/API/custom values are passed through the RDGen-style
    # custom-client inputs. We persist a build manifest for diagnostics.
    manifest={
        "server":a.server,
        "key":a.key,
        "apiServer":a.api,
        "appname":a.appname,
        "filename":a.filename,
        "extras":json.loads(a.extras or "{}"),
        "custom_file_exists":(root/"custom_.txt").exists(),
    }
    (root/".cloud-builder.json").write_text(json.dumps(manifest,indent=2),encoding="utf-8")

    # Branding name patch. This is intentionally conservative; RustDesk source
    # layouts differ between tags, so failing to find a literal must not fail
    # the build.
    if a.appname and a.appname.lower()!="rustdesk":
        replace_text(root,"RustDesk",a.appname)

    print(json.dumps(manifest,indent=2))

if __name__=="__main__":
    main()