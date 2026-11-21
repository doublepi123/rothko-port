# MediaTek IMS APK repair

repair_ims.py rebuilds an IMS APK from caller-supplied artifacts and tools. It applies the checked-in smali patches, adds support DEX 2/3 and ARM64 JNI libraries, and signs with the supplied A17 platform certificate and private key.

Supply the original A17 APK (--base), local working A16 support APK (--support), baksmali and smali Java classpaths, API level, aapt, zipalign, apksigner, A17 platform certificate and matching private key. java, openssl, and the system patch command are used by default and can be overridden. The private key is consumed only by apksigner; never put it in this source tree.

Example:

    python3 tools/pixelos17/ims/repair_ims.py \\
      --base /path/to/original-a17.apk \\
      --support /path/to/local-a16-support.apk \\
      --output /path/to/repaired-ims.apk \\
      --baksmali-classpath /path/to/baksmali.jar \\
      --smali-classpath /path/to/smali.jar \\
      --api 35 \\
      --aapt /path/to/aapt --zipalign /path/to/zipalign \\
      --apksigner /path/to/apksigner \\
      --platform-cert /path/to/platform.x509.pem \\
      --platform-key /path/to/platform.pk8

The base and support APK must have byte-identical `classes.dex` entries. The support APK must include `classes2.dex`, `classes3.dex`, and the 16 stock IMS JNI files under `lib/arm64-v8a/`. The manifest check allows the protected MediaTek carrier broadcast declaration from the working support APK. The supplied certificate must match the original APK signer. The tool checks the output signature, alignment, and imported entries after signing.

The APK contains the JNI files under `lib/arm64-v8a/`. The sibling `.jni` directory contains the same files for placement under `/system_ext/priv-app/RothkoImsService/lib/arm64/`. The sibling `.attestation.json` records input and output SHA-256 hashes, the signer certificate digest, imported DEX names, and a digest for each JNI library.

This is a source-only host procedure. It contains no APKs, tool binaries, certificates, keys, or device-side operations.
