Credential guard vendored unchanged from fzoll/RPI_Hermes PR326,
head4888c9ef5c6371147a05ed6d7c9212edc17331b8 (merged a963ff5c2b396bb28fb37b4f2b49e052c2f000e2).
SHA256 t3_credential_guard.py:
f8fade112ecf952e54d295c6d40d9bc2717252267620b67fd46b1bf630796a75

The image wrapper pins the running T3 CLI/base-dir; receiver pinning and credential
publication remain the tested common protocol. Update this source pin and regression
tests together when vendoring a newer reviewed helper. Never fetch helper code at runtime.
