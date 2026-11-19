#!/usr/bin/env bash
# Phone-side debugging helpers (aarch64, NDK r27c: ./ndk, else ../__shared-third-party__/ndk) -> work/ptrace_log, work/campdump (documentation/development.md):
#   ptrace_log  breakpoint logger for libMC5.so (root, or `run-as` on the debuggable build)
#   campdump    campaign table (chapters -> story mission nodes) from a running game, source of server-data/ah/campaign.json
set -euo pipefail
cd "$(dirname "$0")/.."
tp() { [ -e "$PWD/${2:-$1}" ] && echo "$PWD/${2:-$1}" || echo "${SHARED_3P:-$PWD/../__shared-third-party__}/$1"; }  # third-party: this project first (run from the project root), then ../__shared-third-party__
CC=$(tp ndk)/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android24-clang
$CC -O2 -Wall -Wextra -o work/ptrace_log tools/ptrace_log.c
$CC -O2 -Wall -o work/campdump tools/campdump.c
ls -l work/ptrace_log work/campdump
