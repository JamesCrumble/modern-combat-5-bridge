#!/usr/bin/env bash
# Source this from the repository root: `source env.sh`. Local toolchains only (nothing is installed globally): jdk/, android-sdk/, ndk/.
_P="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export MC5_PROBE="$_P"
export JAVA_HOME="$_P/jdk"
export ANDROID_HOME="$_P/android-sdk"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/build-tools/34.0.0:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
unset _P
