package ai.localmesh.meshcore

import java.util.Base64

// §17.3 encoding rule (binding): all binary-in-JSON/URL values are base64url WITHOUT padding.
// Do not mix standard Base64 (+, /, =) anywhere in the protocol.
object B64Url {

    /** Encodes to base64url with padding stripped (no '=' characters). */
    fun encode(data: ByteArray): String =
        Base64.getUrlEncoder().withoutPadding().encodeToString(data)

    /**
     * Decodes base64url. Tolerates absent padding (the canonical wire form is unpadded, §17.3)
     * and rejects standard-alphabet characters ('+', '/', padding mismatches) with
     * [IllegalArgumentException].
     */
    fun decode(text: String): ByteArray = Base64.getUrlDecoder().decode(text)
}
