package ai.localmesh.meshcore

// Typed bridge error. `code` is surfaced verbatim as the JS rejection code so the TS layer
// (Task 2-b, §11.2 reconciliation) can branch on stable codes.
//
// Codes mandated by the module contract:
//   PIN_REQUIRED, PIN_MISMATCH, HTTP_REJECTED_CLEARTEXT, TLS_HANDSHAKE_FAILED,
//   IDLE_TIMEOUT, CANCELLED, NSD_ERROR, PERMISSION_REQUIRED
// Codes added by this module ([DESIGN], documented in README; reconcile with 2-b):
//   INVALID_REQUEST, TIMEOUT, NETWORK_ERROR, HTTP_ERROR, BODY_TOO_LARGE,
//   KEYSTORE_ERROR, KEY_NOT_FOUND, UNKNOWN
//
// §17.10: never put key material, pairing secrets, tokens, full pins (a 12-char diagnostic prefix
// is the maximum allowed), or any request/response body content into `message`.
class MeshCoreException(
    val code: String,
    message: String,
    cause: Throwable? = null,
) : Exception(message, cause)
