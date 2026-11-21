#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Rebuild a platform-signed IMS APK from caller-provided local inputs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIGNATURE_ENTRY = re.compile(r"META-INF/[^/]+\.(?:SF|RSA|DSA|EC)$", re.IGNORECASE)

def run(args: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.run(args, cwd=cwd, check=True, text=True, stdout=subprocess.PIPE).stdout.strip()

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def entries(path: Path) -> dict[str, zipfile.ZipInfo]:
    with zipfile.ZipFile(path) as apk:
        result = {}
        for item in apk.infolist():
            if item.filename in result:
                raise ValueError(f"duplicate APK entry: {item.filename}")
            result[item.filename] = item
        return result

def cert_digest(openssl: str, cert: Path) -> str:
    for form in ("PEM", "DER"):
        result = subprocess.run([openssl, "x509", "-inform", form, "-in", str(cert), "-outform", "DER"], check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            return digest(result.stdout)
    raise ValueError("platform certificate is not a readable PEM or DER X.509 certificate")

def signer_digest(apksigner: str, apk: Path) -> str:
    output = run([apksigner, "verify", "--print-certs", str(apk)])
    matches = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F:]+)", output)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one APK signer certificate in {apk}")
    return matches[0].replace(":", "").lower()

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, type=Path, help="original A17 built APK")
    parser.add_argument("--support", required=True, type=Path, help="local A16 support APK")
    parser.add_argument("--output", required=True, type=Path, help="new signed APK path; must not exist")
    parser.add_argument("--baksmali-classpath", required=True)
    parser.add_argument("--smali-classpath", required=True)
    parser.add_argument("--api", required=True, type=int)
    parser.add_argument("--aapt", required=True)
    parser.add_argument("--zipalign", required=True)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument("--java", default="java")
    parser.add_argument("--patch", default="patch")
    parser.add_argument("--platform-cert", required=True, type=Path)
    parser.add_argument("--platform-key", required=True, type=Path)
    args = parser.parse_args()
    base, support, output = (p.resolve() for p in (args.base, args.support, args.output))
    cert, key = args.platform_cert.resolve(), args.platform_key.resolve()
    if not all(p.is_file() for p in (base, support, cert, key)):
        raise ValueError("base, support, certificate and key must be existing files")
    if output.exists():
        raise ValueError(f"refusing to overwrite output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    base_entries, support_entries = entries(base), entries(support)
    primary = "classes.dex"
    if primary not in base_entries or primary not in support_entries:
        raise ValueError("both APKs must contain classes.dex")
    with zipfile.ZipFile(base) as bz, zipfile.ZipFile(support) as sz:
        base_primary, support_primary = bz.read(primary), sz.read(primary)
    if digest(base_primary) != digest(support_primary):
        raise ValueError("base and support classes.dex differ; refusing to combine unrelated APKs")
    extra_dex = [n for n in ("classes2.dex", "classes3.dex") if n in support_entries]
    if extra_dex != ["classes2.dex", "classes3.dex"]:
        raise ValueError("support APK must contain both classes2.dex and classes3.dex")
    native = sorted(n for n in support_entries if re.fullmatch(r"lib/arm64-v8a/[^/]+\.so", n))
    if len(native) != 16 or "lib/arm64-v8a/libmtk_vt_wrapper.so" not in native:
        raise ValueError("expected the 16 stock ARM64 IMS JNI libraries")
    if any(n in base_entries for n in (*extra_dex, *native)):
        raise ValueError("support DEX or JNI entry collides with an existing base APK entry")
    manifest = "AndroidManifest.xml"
    base_manifest = run([args.aapt, "dump", "xmltree", "--file", manifest, str(base)]).splitlines()
    support_manifest = run([args.aapt, "dump", "xmltree", "--file", manifest, str(support)]).splitlines()
    action = "com.mediatek.common.carrierexpress.operator_config_changed"
    broadcast = [index for index, line in enumerate(support_manifest) if action in line]
    if len(broadcast) != 1 or broadcast[0] == 0:
        raise ValueError("expected one protected MediaTek carrier broadcast")
    index = broadcast[0]
    if "E: protected-broadcast" not in support_manifest[index - 1] or (
        support_manifest[: index - 1] + support_manifest[index + 1 :] != base_manifest
    ):
        raise ValueError("support manifest differs beyond the carrier broadcast declaration")
    base_signer = signer_digest(args.apksigner, base)
    if base_signer != cert_digest(args.openssl, cert):
        raise ValueError("provided platform certificate does not match original A17 APK signer")

    with tempfile.TemporaryDirectory(prefix="ims-repair-", dir=output.parent) as temporary:
        work = Path(temporary)
        smali_dir, primary_file = work / "smali", work / primary
        primary_file.write_bytes(base_primary)
        run([args.java, "-cp", args.baksmali_classpath, "org.jf.baksmali.Main", "disassemble", "--api", str(args.api), "-o", str(smali_dir), str(primary_file)])
        for patch_name in ("metrics-removal.patch", "wfc-registerReceiver-flags.patch"):
            run([args.patch, "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(HERE / "patches" / patch_name)], cwd=smali_dir)
        patched_dex = work / "patched.dex"
        run([args.java, "-cp", args.smali_classpath, "org.jf.smali.Main", "assemble", "--api", str(args.api), "-o", str(patched_dex), str(smali_dir)])
        unsigned, aligned, signed = work / "unsigned.apk", work / "aligned.apk", work / "signed.apk"
        with zipfile.ZipFile(base) as bz, zipfile.ZipFile(support) as sz, zipfile.ZipFile(unsigned, "w") as target:
            for info in bz.infolist():
                name = info.filename
                if name == primary or name.upper() == "META-INF/MANIFEST.MF" or SIGNATURE_ENTRY.fullmatch(name):
                    continue
                payload = sz.read(manifest) if name == manifest else bz.read(name)
                target.writestr(info, payload)
            target.writestr(base_entries[primary], patched_dex.read_bytes())
            for name in extra_dex:
                target.writestr(support_entries[name], sz.read(name))
            for name in native:
                target.writestr(support_entries[name], sz.read(name), compress_type=zipfile.ZIP_STORED)
        run([args.zipalign, "-P", "16", "4", str(unsigned), str(aligned)])
        run([args.apksigner, "sign", "--cert", str(cert), "--key", str(key), "--out", str(signed), str(aligned)])
        if signer_digest(args.apksigner, signed) != base_signer:
            raise ValueError("signed output certificate differs from original A17 signer")
        run([args.zipalign, "-c", "-P", "16", "4", str(signed)])
        jni_dir = output.parent / (output.name + ".jni")
        if jni_dir.exists():
            raise FileExistsError(jni_dir)
        extracted = work / "jni"
        extracted.mkdir()
        with zipfile.ZipFile(signed) as result, zipfile.ZipFile(support) as source:
            if result.read(primary) != patched_dex.read_bytes():
                raise ValueError("repaired DEX differs after signing")
            for name in (manifest, *extra_dex, *native):
                if result.read(name) != source.read(name):
                    raise ValueError(f"installed support entry differs: {name}")
            jni = {name: digest(result.read(name)) for name in native}
            for name in native:
                (extracted / Path(name).name).write_bytes(result.read(name))
        os.link(signed, output)
        extracted.rename(jni_dir)
    attestation = {"base_sha256": file_digest(base), "support_sha256": file_digest(support), "primary_dex_sha256": digest(base_primary), "output_sha256": file_digest(output), "signer_certificate_sha256": base_signer, "imported_dex": extra_dex, "jni_arm64_sha256": jni}
    output.with_suffix(output.suffix + ".attestation.json").write_text(json.dumps(attestation, indent=2, sort_keys=True) + "\n")
    print(f"Created {output}")
    print(f"JNI libraries embedded and hashed: {len(jni)}")

if __name__ == "__main__":
    main()
