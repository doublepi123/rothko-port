#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare real ARM64 service/handler device layouts using their Ninja flags.

This builds only small host-side compiler probes in --output. It never invokes
Ninja builds or writes to Android source/output. Run after graph regeneration.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, required=True)
parser.add_argument('--graph', required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
root = args.source_root.resolve()
out = args.output.resolve()
out.mkdir(mode=0o700)
base = 'out-clean/soong/.intermediates/device/xiaomi/rothko/udfps/'
objects = {
    'handler': base + 'librothko_udfpshandler/android_vendor_arm64_armv8-2a_static/obj/device/xiaomi/rothko/udfps/RothkoUdfpsHandler.o',
    'service': base + 'android.hardware.biometrics.fingerprint-service.rothko-prebuilt-vendor/android_vendor_arm64_armv8-2a/obj/hardware/xiaomi/aidl/fingerprint/Session.o',
}
probe = out / 'layout.cpp'
probe.write_text('#include <stddef.h>\n#include "UdfpsHandler.h"\n'
                 'extern "C" unsigned long extcmd_offset() { return offsetof(fingerprint_device_t, extCmd); }\n'
                 'extern "C" unsigned long authenticate_offset() { return offsetof(fingerprint_device_t, authenticate); }\n')
report = {'status': 'started', 'phone_operations': False, 'layouts': {}}
commands = {}
try:
    for name, target in objects.items():
        result = subprocess.run([str(root / 'prebuilts/build-tools/linux-x86/bin/ninja'),
                                 '-f', args.graph, '-t', 'commands', target],
                                cwd=root, capture_output=True, text=True, check=True)
        command = result.stdout.splitlines()[-1]
        (out / (name + '-compile-command.txt')).write_text(command + '\n')
        tokens = shlex.split(command)
        assert tokens.pop(0) == 'PWD=/proc/self/cwd'
        assert not {'&&', ';', '|'} & set(tokens)
        compile_args = []
        i = 0
        while i < len(tokens):
            if tokens[i] in ('-o', '-MF'):
                i += 2
                continue
            if tokens[i] in ('-c', '-MD', '-MMD') or tokens[i].endswith('.cpp'):
                i += 1
                continue
            compile_args.append(tokens[i])
            i += 1
        commands[name] = compile_args
        ir = out / (name + '.ll')
        run = subprocess.run([*compile_args, '-S', '-emit-llvm', '-o', str(ir), str(probe)],
                             cwd=root, capture_output=True, text=True)
        (out / (name + '.log')).write_text(run.stdout + run.stderr)
        assert run.returncode == 0, name + ': compiler probe failed'
        values = {}
        for function in ('extcmd_offset', 'authenticate_offset'):
            match = re.search(r'define[^@]*@' + function
                              + r'\([^)]*\)[^{]*\{.*?ret i64 (\d+)', ir.read_text(), re.S)
            assert match, name + ': missing ARM64 constant'
            values[function] = int(match.group(1))
        report['layouts'][name] = {**values, 'impl_v2': '-DIMPL_V2' in compile_args,
                                  'command_sha256': hashlib.sha256(command.encode()).hexdigest()}
    assert all(row['impl_v2'] for row in report['layouts'].values()), 'V2 flag missing'
    assert report['layouts']['handler']['extcmd_offset'] == report['layouts']['service']['extcmd_offset'], 'Device table ABI mismatch'
    assert report['layouts']['handler']['extcmd_offset'] != report['layouts']['service']['authenticate_offset'], 'extCmd would call authenticate'
    negative = [arg for arg in commands['handler'] if arg != '-DIMPL_V2']
    run = subprocess.run([*negative, '-fsyntax-only', 'device/xiaomi/rothko/udfps/RothkoUdfpsHandler.cpp'],
                         cwd=root, capture_output=True, text=True)
    (out / 'v1-rejected.log').write_text(run.stdout + run.stderr)
    assert run.returncode != 0 and 'requires the same Xiaomi V2 device ABI' in run.stderr, 'V1 compilation was not rejected'
    report.update(status='arm64-service-handler-v2-layout-and-negative-guard-verified',
                  v1_compile_rejected=True)
except BaseException as error:
    report.update(status='failed', error=repr(error))
(out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2), flush=True)
raise SystemExit(0 if report['status'] == 'arm64-service-handler-v2-layout-and-negative-guard-verified' else 1)
