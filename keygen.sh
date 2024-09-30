#!/bin/bash

set -euo pipefail

keytool -genkey \
        -storepass pwpwpw -keypass pwpwpw \
        -dname "CN=Debuggable, OU=Debuggable, O=Debuggable, L=Mende, S=Pest, C=HU" \
        -v -keystore debuggable.keystore -keyalg RSA -keysize 2048 -validity 100000 -alias debuggable
