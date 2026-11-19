#!/bin/bash
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail
umask 077
if [[ $# != 1 || -e $1 || -L $1 ]]; then
    echo "Usage: $0 <new-private-key-directory> (destination must not exist)" >&2
    exit 2
fi
key_dir=$1
mkdir -p -- "$key_dir"
temporary=$(mktemp -d "$key_dir/.keygen.XXXXXX")
trap 'rm -rf -- "$temporary"' EXIT
for name in releasekey testkey platform shared media networkstack sdk_sandbox bluetooth nfc; do
    openssl genpkey -quiet -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
        -out "$temporary/private.pem"
    openssl pkcs8 -topk8 -inform PEM -outform DER -nocrypt \
        -in "$temporary/private.pem" -out "$key_dir/$name.pk8"
    openssl req -new -x509 -days 3650 -key "$temporary/private.pem" \
        -out "$key_dir/$name.x509.pem" \
        -subj "/CN=Rothko development $name/OU=Disposable clean build/"
done
echo "Generated nine disposable development certificate/key pairs."
