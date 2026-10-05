package ai.localmesh.meshcore

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.InputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.security.KeyStore
import java.security.MessageDigest
import java.security.cert.Certificate
import java.security.cert.CertificateFactory
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Base64
import javax.net.ssl.KeyManagerFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLServerSocket
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/**
 * WP-09 instrumented tests (§11.2, §17.3, §17.9, §6.4) — run on a device or
 * emulator: `./gradlew :mesh-core:connectedDebugAndroidTest`.
 *
 * Covered acceptance criteria (spec WP table, WP-09 row):
 *   - "Pin mandatory; HTTPS only; no key export"
 *   - "Instrumented tests; pin-mismatch test"
 *   - FR-PAIR-03: "Pin mismatch aborts pairing with no request body sent
 *     (verified by test server)"
 *
 * A loopback TLS 1.3 server presents a REAL self-signed EC P-256 certificate
 * loaded from `androidTest/assets/agent-cert.pem` + `agent-key.pem`
 * (PKCS#8; generate with openssl per the module README).
 */
@RunWith(AndroidJUnit4::class)
class PinnedHttpInstrumentedTest {

    // ---------------------------------------------------------------------
    // Local TLS test server (self-signed EC P-256, TLS 1.3 only)
    // ---------------------------------------------------------------------

    private class TlsServer : AutoCloseable {
        val serverSocket: SSLServerSocket
        val spkiSha256B64Url: String
        val receivedBodies: MutableList<String> = mutableListOf()

        init {
            val assets = InstrumentationRegistry.getInstrumentation().context.assets
            val cert = assets.open("agent-cert.pem").use(::readPemCertificate)
            val key = assets.open("agent-key.pem").use(::readPkcs8Key)

            val ks = KeyStore.getInstance(KeyStore.getDefaultType())
            ks.load(null, null)
            ks.setKeyEntry("agent", key, charArrayOf(), arrayOf(cert))
            val kmf = KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm())
            kmf.init(ks, charArrayOf())
            val ctx = SSLContext.getInstance("TLSv1.3") // §17.3: TLS 1.3 only
            ctx.init(kmf.keyManagers, null, null)
            serverSocket = ctx.serverSocket as SSLServerSocket
            serverSocket.bind(InetSocketAddress(InetAddress.getLoopbackAddress(), 0))
            serverSocket.enabledProtocols = arrayOf("TLSv1.3")

            // §17.3: pin = SHA-256 over DER SubjectPublicKeyInfo, base64url-no-pad.
            val digest = MessageDigest.getInstance("SHA-256").digest(cert.publicKey.encoded)
            spkiSha256B64Url = Base64.getUrlEncoder().withoutPadding().encodeToString(digest)
        }

        fun url(path: String): String = "https://127.0.0.1:${serverSocket.localPort}$path"

        /** Accept one connection, read headers (+ optional body), respond 200 JSON. */
        fun serveOnce(body: String = "{\"ok\":true}") {
            val socket = serverSocket.accept()
            socket.use { s ->
                val reader = s.inputStream.bufferedReader()
                var line: String?
                var contentLength = 0
                while (reader.readLine().also { line = it } != null) {
                    if (line.equals("", ignoreCase = true)) break
                    if (line!!.startsWith("Content-Length", ignoreCase = true)) {
                        contentLength = line!!.substringAfter(':').trim().toInt()
                    }
                }
                if (contentLength > 0) {
                    val buf = CharArray(contentLength)
                    var read = 0
                    while (read < contentLength) read += reader.read(buf, read, contentLength - read)
                    receivedBodies.add(String(buf))
                }
                val resp =
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: ${body.length}\r\nConnection: close\r\n\r\n$body"
                s.outputStream.write(resp.toByteArray())
                s.outputStream.flush()
            }
        }

        override fun close() {
            serverSocket.close()
        }
    }

    private fun baseReq(url: String, pin: String, body: Map<String, Any?>? = null): MutableMap<String, Any?> =
        mutableMapOf(
            "url" to url,
            "method" to (if (body != null) "POST" else "GET"),
            "pinSpkiSha256B64Url" to pin,
            "timeoutMs" to 5000L,
        ).apply { body?.let { put("bodyJson", it) } }

    // ---------------------------------------------------------------------
    // Pin is mandatory (§11.2: "no overload without it") — fails closed
    // BEFORE any socket is opened, i.e. before any secret could be sent.
    // ---------------------------------------------------------------------

    @Test
    fun missingPin_failsClosedWithPinRequired_beforeAnySocket() {
        val ex = assertThrows(MeshCoreException::class.java) {
            PinnedHttp.resolveTarget(
                mapOf("url" to "https://127.0.0.1:1/mesh/v1/info", "method" to "GET", "timeoutMs" to 1000L),
                allowDebugCleartext = false,
                requireBody = false,
                requireTimeoutMs = true,
            )
        }
        assertEquals("PIN_REQUIRED", ex.code)
    }

    @Test
    fun malformedPin_failsClosedWithPinRequired() {
        val ex = assertThrows(MeshCoreException::class.java) {
            PinnedHttp.resolveTarget(
                mapOf(
                    "url" to "https://127.0.0.1:1/mesh/v1/info",
                    "method" to "GET",
                    "pinSpkiSha256B64Url" to "not base64url!!",
                    "timeoutMs" to 1000L,
                ),
                allowDebugCleartext = false,
                requireBody = false,
                requireTimeoutMs = true,
            )
        }
        assertEquals("PIN_REQUIRED", ex.code)
    }

    // ---------------------------------------------------------------------
    // HTTPS only (SEC-N1); §17.9 debug carve-out is 10.0.2.2 / 127.0.0.1 ONLY
    // ---------------------------------------------------------------------

    @Test
    fun debugCleartextHostSet_isEmulatorOnly() {
        // §17.9: cleartext is allowed ONLY to 10.0.2.2 / 127.0.0.1 in debug.
        assertEquals(setOf("10.0.2.2", "127.0.0.1"), PinnedHttp.DEBUG_CLEARTEXT_HOSTS)
    }

    @Test
    fun httpUrl_rejectedWithCleartextCode_inRelease() {
        val ex = assertThrows(MeshCoreException::class.java) {
            PinnedHttp.resolveTarget(
                mapOf(
                    "url" to "http://192.168.1.50:8443/mesh/v1/info",
                    "method" to "GET",
                    "pinSpkiSha256B64Url" to PIN32,
                    "timeoutMs" to 1000L,
                ),
                allowDebugCleartext = false,
                requireBody = false,
                requireTimeoutMs = true,
            )
        }
        assertEquals("HTTP_REJECTED_CLEARTEXT", ex.code)
    }

    @Test
    fun httpUrl_rejectedEvenInDebug_forNonEmulatorHost() {
        val ex = assertThrows(MeshCoreException::class.java) {
            PinnedHttp.resolveTarget(
                mapOf(
                    "url" to "http://192.168.1.50:8443/mesh/v1/info",
                    "method" to "GET",
                    "pinSpkiSha256B64Url" to PIN32,
                    "timeoutMs" to 1000L,
                ),
                allowDebugCleartext = true, // debug build
                requireBody = false,
                requireTimeoutMs = true,
            )
        }
        // §17.9 carve-out is 10.0.2.2 / 127.0.0.1 ONLY — a LAN IP stays rejected.
        assertEquals("HTTP_REJECTED_CLEARTEXT", ex.code)
    }

    @Test
    fun httpUrl_allowedInDebug_forEmulatorHostOnly() {
        val target = PinnedHttp.resolveTarget(
            mapOf(
                "url" to "http://10.0.2.2:8443/mesh/v1/info", // CI-10 emulator mapping
                "method" to "GET",
                "pinSpkiSha256B64Url" to PIN32,
                "timeoutMs" to 1000L,
            ),
            allowDebugCleartext = true,
            requireBody = false,
            requireTimeoutMs = true,
        )
        assertEquals("10.0.2.2", target.url.host)
    }

    // ---------------------------------------------------------------------
    // Happy path + observed SPKI echo (§11.2: return tlsSpkiSha256B64Url)
    // ---------------------------------------------------------------------

    @Test
    fun pinnedRequest_succeeds_andEchoesObservedSpki() {
        TlsServer().use { server ->
            Thread { server.serveOnce() }.start()
            val result = PinnedHttp.request(baseReq(server.url("/mesh/v1/info"), server.spkiSha256B64Url), allowDebugCleartext = false)
            assertEquals(200, result.status)
            // §11.2: "tlsSpkiSha256B64Url returned so the JS layer can assert equality"
            assertEquals(server.spkiSha256B64Url, result.tlsSpkiSha256B64Url)
        }
    }

    // ---------------------------------------------------------------------
    // THE pin-mismatch test (WP-09 acceptance; CI-12; FR-PAIR-03)
    // ---------------------------------------------------------------------

    @Test
    fun pinMismatch_failsWithPinMismatchCode_andNoRequestBodyReachesTheWire() {
        TlsServer().use { server ->
            // A valid but DIFFERENT 32-byte pin (rotated-identity scenario, CI-12).
            val other = ByteArray(32) { (it * 7 + 1).toByte() }
            val wrongPin = Base64.getUrlEncoder().withoutPadding().encodeToString(other)
            assertNotEquals(server.spkiSha256B64Url, wrongPin)

            // The server WOULD accept a pair/complete-shaped POST; if the client
            // leaked the body before the TLS pin check, FR-PAIR-03 is broken.
            Thread { server.serveOnce(body = "{\"accepted\":true}") }.start()

            val req = baseReq(server.url("/mesh/v1/pair/complete"), wrongPin, body = mapOf("meta" to "pairing-payload"))
            val ex = assertThrows(MeshCoreException::class.java) {
                PinnedHttp.request(req, allowDebugCleartext = false)
            }
            assertEquals("PIN_MISMATCH", ex.code)
            // FR-PAIR-03: "Pin mismatch aborts pairing with no request body sent"
            assertEquals(0, server.receivedBodies.size)
        }
    }

    private companion object {
        /** 32 bytes of pin-shaped base64url (no padding) — syntactically valid, semantically wrong. */
        val PIN32 = Base64.getUrlEncoder().withoutPadding()
            .encodeToString(ByteArray(32) { (it * 3 + 5).toByte() })
    }
}

/** Read the FIRST certificate out of a PEM stream. */
private fun readPemCertificate(input: InputStream): Certificate {
    val pem = input.readBytes().decodeToString()
    val b64 = pem
        .substringAfter("-----BEGIN CERTIFICATE-----")
        .substringBefore("-----END CERTIFICATE-----")
        .filterNot { it == '\r' || it == '\n' || it == ' ' }
    val der = Base64.getMimeDecoder().decode(b64)
    return CertificateFactory.getInstance("X.509").generateCertificate(der.inputStream())
}

/** Read a PKCS#8 PEM private key (openssl: `openssl pkey -outform pem` default). */
private fun readPkcs8Key(input: InputStream): java.security.PrivateKey {
    val pem = input.readBytes().decodeToString()
    val b64 = pem
        .substringAfter("-----BEGIN PRIVATE KEY-----")
        .substringBefore("-----END PRIVATE KEY-----")
        .filterNot { it == '\r' || it == '\n' || it == ' ' }
    val der = Base64.getMimeDecoder().decode(b64)
    return java.security.KeyFactory.getInstance("EC").generatePrivate(PKCS8EncodedKeySpec(der))
}
