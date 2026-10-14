"""Offline release review manifest creation and Ed25519 signing.

Supply the private key from independently managed secure custody, never CI
source control or a repository secret. The command only signs local review
artifacts; distribution and key trust remain separate release gates.
"""
import argparse
import hashlib
import json
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from src.governance.release_verification import canonical_manifest,verify_release


def create_signed_manifest(directory,*,source_commit,key_file):
    root=Path(directory).resolve(strict=True)
    key_path=Path(key_file)
    if key_path.is_symlink() or not key_path.is_file():
        raise ValueError("signing key must be a regular local file")
    if os.name=="posix" and stat.S_IMODE(key_path.stat().st_mode)&0o077:
        raise ValueError("signing key must be owner-only")
    raw=key_path.read_bytes()
    if len(raw)!=32:
        raise ValueError("raw Ed25519 signing private key must contain 32 bytes")
    paths=[p for p in sorted(root.iterdir()) if p.is_file() and not p.is_symlink()]
    if not paths or any(p.name.endswith((".sig",".manifest.json")) for p in paths):
        raise ValueError("sign only a clean artifact directory without old manifests")
    entries={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    manifest={"version":1,"source_commit":source_commit,"artifacts":entries}
    digest=canonical_manifest(manifest)
    signer=Ed25519PrivateKey.from_private_bytes(raw)
    return manifest,signer.sign(digest).hex()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--artifact-dir",required=True)
    ap.add_argument("--source-commit",required=True)
    ap.add_argument("--private-key-file",required=True)
    ap.add_argument("--output-prefix",required=True)
    args=ap.parse_args()
    manifest,sig=create_signed_manifest(
        args.artifact_dir,source_commit=args.source_commit,key_file=args.private_key_file)
    Path(args.output_prefix+".manifest.json").write_text(
        json.dumps(manifest,indent=2,sort_keys=True)+"\n")
    Path(args.output_prefix+".sig").write_text(sig+"\n")
    print(json.dumps({"signed_artifacts":len(manifest["artifacts"]),
                      "source_commit":manifest["source_commit"]}))


if __name__=="__main__":
    main()
