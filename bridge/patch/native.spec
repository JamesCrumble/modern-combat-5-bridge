# Byte patches of libMC5.so (Play 6.0.12a, arm64); one logic for the PC build and the phone (documentation/architecture.md).
# file NAME [sha256 HEX]               the library inside the arm64 split (the original is checked against the hash)
# string OLD => NEW                    replace a C string (NEW must not be longer; the rest is NUL), every occurrence, at least one
# bytes OFFSET OLD => NEW              replace bytes at a file offset (hex); OLD must be there
# if NAME                              the next directives apply only when the build option NAME is on (default options: see Patcher)
file lib/arm64-v8a/libMC5.so sha256 5834acb133277a466f915adc84c786495c72e6ccad7d9b9b15715e34384c3751
string https://eve.gameloft.com => ${EVE_URL}
# TLS_NOVERIFY: the client accepts any server certificate (no root CA on the phone). In the static OpenSSL 1.1.1:
#   X509_verify_cert (0x11908b8) -> "mov w0,#1; ret"; ssl_verify_cert_chain: the app_verify_callback branch (0x10fc644 cbz) -> always X509_verify_cert.
if TLS_NOVERIFY
bytes 11908b8 f44fbea9fd7b01a9 => 20008052c0035fd6
bytes 10fc644 a80300b4 => 1d000014
# IAP_NOVERIFY: the IAP library checks the e-commerce answer (header X-InApp-Hash); our server cannot sign: the verify function (0xd05648) returns 0 ("valid").
if IAP_NOVERIFY
bytes d05648 ff0304d1f95b00f9 => e0031f2ac0035fd6
