"""Read-only proof of the actual, approved Kati cleanspec ancestor."""
import os
from pathlib import Path
import re


def source_root(device_root):
    root = Path(device_root).resolve().parents[2]
    return root if (root / "prebuilts/build-tools/linux-x86/bin/ckati").is_file() else root / "source"


def classify(argv, executable, cwd, root):
    root = Path(root).resolve()
    approved = {(root / "prebuilts/build-tools/linux-x86/bin" / name).resolve()
                for name in ("ckati", "rkati") if (root / "prebuilts/build-tools/linux-x86/bin" / name).is_file()}
    entry = [argv[i + 1] for i, token in enumerate(argv[:-1]) if token == "-f"]
    suffix = [x.split("=", 1)[1] for x in argv if x.startswith("--ninja_suffix=")]
    result = {"approved_cleanspec": False, "executable": str(executable),
              "entrypoints": entry, "ninja_suffixes": suffix, "ninja_mode": "--ninja" in argv}
    if Path(executable).resolve() not in approved:
        return result
    if len(entry) != 1 or len(suffix) != 1 or "--ninja" not in argv:
        return result
    path = Path(entry[0])
    path = path if path.is_absolute() else Path(cwd) / path
    result["resolved_entrypoint"] = str(path.resolve())
    result["approved_cleanspec"] = (
        path.resolve() == root / "build/make/core/cleanbuild.mk"
        and bool(re.fullmatch(r"-(?:lineage|custom)_rothko(?:-[A-Za-z0-9_-]+)?-cleanspec", suffix[0]))
        and not any(token.startswith("--file") or (token.startswith("-f") and token != "-f") for token in argv[1:])
    )
    return result


def inspect(device_root):
    root = source_root(device_root)
    pid = os.getppid()
    for _ in range(24):
        if pid <= 1:
            break
        proc = Path("/proc") / str(pid)
        try:
            argv = [x.decode(errors="replace") for x in (proc / "cmdline").read_bytes().split(b"\0") if x]
            executable = (proc / "exe").resolve()
            cwd = (proc / "cwd").resolve()
            if executable.name in ("ckati", "rkati"):
                result = classify(argv, executable, cwd, root)
                result["pid"] = pid
                return result
            status = (proc / "status").read_text()
            pid = int(re.search(r"^PPid:\s+(\d+)", status, re.M).group(1))
        except (OSError, ValueError, AttributeError):
            break
    return {"approved_cleanspec": False, "reason": "No verified approved Kati ancestor"}
