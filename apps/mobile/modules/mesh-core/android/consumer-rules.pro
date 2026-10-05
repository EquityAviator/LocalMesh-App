# mesh-core consumer ProGuard rules
#
# The module relies on runtime-reflective surfaces that must survive R8 in release builds:
# - AndroidKeyStore KeySpec introspection (android.security.keystore.KeyInfo) is framework code —
#   never stripped, no rule needed.
# - org.json is a framework stub on-device — no rule needed.
# - OkHttp consumer rules are shipped by the artifact itself.
#
# Explicitly kept empty of -dontobfuscate: release builds stay fully optimized (§17.8 App hardening).
# If a future dependency needs rules, add them here with the spec citation that introduced it.
