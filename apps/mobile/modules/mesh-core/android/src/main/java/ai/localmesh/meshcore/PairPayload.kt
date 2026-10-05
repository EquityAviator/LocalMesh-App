package ai.localmesh.meshcore

import java.net.URI
import java.net.URLDecoder

// §17.4 QR payload — normative shape:
//   localmesh://pair?v=1&aid=<agent_id>&n=<urlencoded name>&fp=<pin>&pid=<pair_id>&sec=<b64url 32B>
//             &ep=<urlencoded https endpoint>[&ep=…]
//
// Pure Kotlin (no android.* imports) so it is unit-testable on the JVM (test/QrPayloadTest.kt).
// Used by the pairing confirm flow to validate and render the deep link BEFORE any request is made
// (§17.8 App hardening: deep links are validated and require user confirmation before any request).
//
// §17.4: `sec` is the only intentional secret exposure in the whole payload — it must never be
// written to logs, clipboard, or shown beyond the confirm screen. This class therefore overrides
// toString() to redact it (§17.10).
data class PairPayload(
    val version: String,
    val agentId: String,
    val displayName: String,
    val fingerprint: String,
    val pairId: String,
    val pairingSecretB64Url: String,
    val endpoints: List<String>,
) {
    override fun toString(): String = redacted()

    /** Log/render-safe representation: fp truncated to 12 chars, sec fully redacted (§17.10). */
    fun redacted(): String =
        "PairPayload(v=$version, aid=$agentId, n=$displayName, fp=${fingerprint.take(12)}…, " +
            "pid=$pairId, sec=<redacted>, eps=${endpoints.size})"

    companion object {
        const val SCHEME = "localmesh"
        const val HOST = "pair"

        /** §17.3: pairing secret is a CSPRNG 32-byte value. */
        const val SECRET_BYTES = 32

        fun parse(uriText: String): PairPayload {
            val uri = try {
                URI(uriText)
            } catch (e: Exception) {
                throw IllegalArgumentException("malformed $SCHEME:// URI", e)
            }
            if (!SCHEME.equals(uri.scheme, ignoreCase = true)) {
                throw IllegalArgumentException("expected scheme $SCHEME://, got '${uri.scheme}'")
            }
            if (uri.host == null || !HOST.equals(uri.host, ignoreCase = true)) {
                throw IllegalArgumentException("expected $SCHEME://$HOST, got host=${uri.host}")
            }
            val rawQuery = uri.rawQuery ?: throw IllegalArgumentException("missing query parameters")

            val params = LinkedHashMap<String, MutableList<String>>()
            for (piece in rawQuery.split('&')) {
                if (piece.isEmpty()) continue
                val idx = piece.indexOf('=')
                val key = if (idx < 0) piece else piece.substring(0, idx)
                val rawValue = if (idx < 0) "" else piece.substring(idx + 1)
                // URLDecoder maps '+' to ' '; base64url (§17.3) contains no '+' and producers
                // percent-encode reserved bytes, so this matches the §17.4 encoding convention.
                val value = try {
                    URLDecoder.decode(rawValue, "UTF-8")
                } catch (e: Exception) {
                    throw IllegalArgumentException("malformed percent-encoding in query parameter '$key'")
                }
                params.getOrPut(key) { mutableListOf() }.add(value)
            }

            val v = params["v"]?.firstOrNull() ?: throw IllegalArgumentException("missing v")
            if (v != "1") throw IllegalArgumentException("unsupported payload version v=$v")

            val aid = requireField(params, "aid")
            val fp = requireField(params, "fp")
            val pid = requireField(params, "pid")
            val sec = requireField(params, "sec")
            val displayName = params["n"]?.firstOrNull() ?: ""
            val eps = params["ep"] ?: throw IllegalArgumentException("missing ep (https endpoint)")
            for (ep in eps) {
                // §6.4: cleartext is blocked by default; §17.4: ep is an https endpoint.
                if (!ep.startsWith("https://")) {
                    throw IllegalArgumentException("ep must be an https:// endpoint (SEC-N1)")
                }
            }

            val secretBytes = try {
                B64Url.decode(sec)
            } catch (e: IllegalArgumentException) {
                throw IllegalArgumentException("sec is not valid base64url", e)
            }
            if (secretBytes.size != SECRET_BYTES) {
                throw IllegalArgumentException("sec must decode to $SECRET_BYTES bytes (§17.3)")
            }

            return PairPayload(version = v, agentId = aid, displayName = displayName,
                fingerprint = fp, pairId = pid, pairingSecretB64Url = sec, endpoints = eps)
        }

        private fun requireField(params: Map<String, List<String>>, key: String): String =
            params[key]?.firstOrNull()?.takeIf { it.isNotEmpty() }
                ?: throw IllegalArgumentException("missing $key")
    }
}
