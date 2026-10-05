package ai.localmesh.meshcore

import java.io.IOException
import java.io.InterruptedIOException
import java.net.InetAddress
import java.net.Socket
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.CertificateExpiredException
import java.security.cert.CertificateNotYetValidException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import javax.net.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory
import javax.net.ssl.SSLException
import javax.net.ssl.SSLHandshakeException
import javax.net.ssl.SSLPeerUnverifiedException
import javax.net.ssl.TrustManager
import javax.net.ssl.X509TrustManager
import okhttp3.ConnectionSpec
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.TlsVersion
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

// §11.2 pinned HTTP (JSON) — request() per the normative contract:
//   request(req: { url; method 'GET'|'POST'|'DELETE'; headers?; bodyJson?; pinSpkiSha256B64Url; timeoutMs })
//     → { status; headers; bodyJson?; tlsSpkiSha256B64Url }
//
// Security invariants implemented here:
// - §11.2 rule: the pin is MANDATORY on every call — empty/missing/undecodable pin fails closed
//   with PIN_REQUIRED before any socket is opened.
// - §17.3 (binding): Agent identity pin = SHA-256 over the DER SubjectPublicKeyInfo of the LEAF
//   certificate, encoded base64url no-padding, compared constant-time (MessageDigest.isEqual).
//   The Agent cert is self-signed; there is NO CA trust and NO hostname check by design — the pin
//   is the identity (§17.3; T-20/T-21: mDNS adverts and hostnames are untrusted hints).
// - §17.8 T-22 / SEC-N1: TLS 1.3 only (ConnectionSpec + hardening socket factory); cleartext HTTP
//   is rejected outright except the §17.9 debug-only emulator carve-out
//   (BuildConfig.DEBUG && host ∈ {10.0.2.2, 127.0.0.1}).
// - §17.9: the carve-out is compiled out of release builds because the release library variant
//   has BuildConfig.DEBUG == false.
// - §17.10: no URL/host echo beyond what the JS caller already knows; no body content in errors.
object PinnedHttp {

    /** §17.9: debug-build cleartext is only ever allowed to the emulator host loopback. */
    val DEBUG_CLEARTEXT_HOSTS = setOf("10.0.2.2", "127.0.0.1")

    /**
     * §15.x CI-18: the mobile App drops an SSE stream with no bytes for 45 s. That budget lives in
     * the JS layer; [DEFAULT_IDLE_TIMEOUT_MS] is only the fallback when `idleTimeoutMs` is absent
     * from an openStream() call ([DESIGN]).
     */
    const val DEFAULT_IDLE_TIMEOUT_MS = 45_000L

    /** [DESIGN] OOM guard: cap on how much of a response body is read before BODY_TOO_LARGE. */
    const val MAX_BODY_BYTES: Long = 16L * 1024L * 1024L

    private const val JSON_MEDIA = "application/json; charset=utf-8"

    data class RequestResult(
        val status: Int,
        val headers: Map<String, String>,
        val bodyJson: Any?,
        val tlsSpkiSha256B64Url: String,
    )

    /** Argument container shared by request() and SseStream (openStream). */
    class PinnedTarget(
        val url: HttpUrl,
        val pinBytes: ByteArray,
        val method: String,
        val headers: Map<String, String>,
        val bodyJsonText: String?,
        val timeoutMs: Long,
        val idleTimeoutMs: Long,
    )

    /**
     * Validates and resolves the §11.2 request shape. Throws [MeshCoreException] (fail closed)
     * before anything touches the network.
     */
    fun resolveTarget(
        req: Map<String, Any?>,
        allowDebugCleartext: Boolean,
        requireBody: Boolean,
        requireTimeoutMs: Boolean,
    ): PinnedTarget {
        // §11.2: "the pin is mandatory on every call (no overload without it)".
        val pinRaw = req["pinSpkiSha256B64Url"] as? String
        if (pinRaw.isNullOrEmpty()) {
            throw MeshCoreException("PIN_REQUIRED", "pinSpkiSha256B64Url is mandatory on every call (§11.2)")
        }
        val pinBytes = try {
            B64Url.decode(pinRaw)
        } catch (e: IllegalArgumentException) {
            throw MeshCoreException("PIN_REQUIRED", "pinSpkiSha256B64Url is not valid base64url")
        }
        if (pinBytes.isEmpty()) {
            throw MeshCoreException("PIN_REQUIRED", "pinSpkiSha256B64Url decodes to zero bytes")
        }

        val rawUrl = req["url"] as? String
        if (rawUrl.isNullOrEmpty()) throw MeshCoreException("INVALID_REQUEST", "url is required")
        val url = rawUrl.toHttpUrlOrNull()
            ?: throw MeshCoreException("INVALID_REQUEST", "url is not a valid absolute URL")

        if (url.scheme != "https") {
            // §17.9 debug-only carve-out: cleartext to the emulator host loopback, never elsewhere.
            val debugOk = url.scheme == "http" &&
                allowDebugCleartext &&
                url.host in DEBUG_CLEARTEXT_HOSTS
            if (!debugOk) {
                throw MeshCoreException(
                    "HTTP_REJECTED_CLEARTEXT",
                    "only https:// URLs are allowed (SEC-N1); debug builds may additionally use " +
                        "http:// to ${DEBUG_CLEARTEXT_HOSTS} (§17.9)",
                )
            }
        }

        val method = (req["method"] as? String)?.uppercase() ?: ""
        if (method !in setOf("GET", "POST", "DELETE")) {
            throw MeshCoreException("INVALID_REQUEST", "method must be GET, POST or DELETE (§11.2)")
        }

        val headers = (req["headers"] as? Map<*, *>)
            ?.mapKeys { it.key.toString() }
            ?.mapValues { it.value?.toString() ?: "" }
            ?: emptyMap()

        val bodyJsonText = when (val bodyJson = req["bodyJson"]) {
            null -> null
            else -> {
                val wrapped = JSONObject.wrap(bodyJson)
                    ?: throw MeshCoreException("INVALID_REQUEST", "bodyJson is not JSON-serializable")
                wrapped.toString()
            }
        }
        if (requireBody && bodyJsonText == null) {
            throw MeshCoreException("INVALID_REQUEST", "bodyJson is required for openStream (§11.2)")
        }

        val timeoutMs = (req["timeoutMs"] as? Number)?.toLong() ?: 0L
        if (requireTimeoutMs && timeoutMs <= 0L) {
            throw MeshCoreException("INVALID_REQUEST", "timeoutMs is required and must be positive (§11.2)")
        }
        val idleTimeoutMs = (req["idleTimeoutMs"] as? Number)?.toLong()?.takeIf { it > 0L }
            ?: DEFAULT_IDLE_TIMEOUT_MS

        return PinnedTarget(url, pinBytes, method, headers, bodyJsonText, timeoutMs, idleTimeoutMs)
    }

    /** One-shot pinned request. Blocking — run on a worker thread (MeshCoreModule does). */
    fun request(req: Map<String, Any?>, allowDebugCleartext: Boolean): RequestResult {
        val target = resolveTarget(req, allowDebugCleartext, requireBody = false, requireTimeoutMs = true)
        val trustManager = PinningTrustManager(target.pinBytes)
        val client = buildPinnedClient(
            trustManager,
            allowDebugCleartext,
            connectTimeoutMs = target.timeoutMs,
            callTimeoutMs = target.timeoutMs,
            readTimeoutMs = target.timeoutMs,
        )
        try {
            client.newCall(buildRequest(target)).execute().use { response ->
                val tlsPin = response.handshake?.peerCertificates?.firstOrNull()
                    ?.let { cert -> (cert as? X509Certificate)?.let { pinOf(it) } }
                    ?: "" // §17.9 cleartext debug path observes no TLS — JS asserts only on https
                val headers = LinkedHashMap<String, String>()
                response.headers.forEach { (name, value) ->
                    val existing = headers[name]
                    headers[name] = if (existing == null) value else "$existing, $value"
                }
                val bodyText = readBounded(response)
                return RequestResult(response.code, headers, parseJsonOrNull(bodyText), tlsPin)
            }
        } catch (e: Throwable) {
            throw classifyNetworkError(e, trustManager.mismatch.get())
        }
    }

    // ---------------------------------------------------------------- client construction

    /**
     * Builds an OkHttpClient whose ONLY trust anchor is the pin. Exposed (public) because the
     * instrumented tests assert the TLS 1.3-only socket factory directly.
     */
    fun buildPinnedClient(
        trustManager: PinningTrustManager,
        allowDebugCleartext: Boolean,
        connectTimeoutMs: Long,
        callTimeoutMs: Long,
        readTimeoutMs: Long,
    ): OkHttpClient {
        val sslContext = SSLContext.getInstance("TLS")
        sslContext.init(null, arrayOf<TrustManager>(trustManager), null)
        val tls13Spec = ConnectionSpec.Builder(ConnectionSpec.RESTRICTED_TLS)
            .tlsVersions(TlsVersion.TLS_1_3) // §17.3: TLS 1.3 only (T-22 downgrade ban)
            .build()
        val specs = if (allowDebugCleartext) {
            listOf(tls13Spec, ConnectionSpec.CLEARTEXT) // §17.9 debug carve-out only
        } else {
            listOf(tls13Spec)
        }
        return OkHttpClient.Builder()
            .sslSocketFactory(Tls13OnlySocketFactory(sslContext.socketFactory), trustManager)
            .connectionSpecs(specs)
            // §17.3: identity is the SPKI pin. The Agent cert SAN is `localmesh-agent` and we dial
            // literal discovered IPs, so hostname verification is meaningless here — deliberately
            // replaced by pin-only validation (T-20/T-21). Not a security weakening: without the
            // pin the request never leaves the device at all (PIN_REQUIRED).
            .hostnameVerifier(AllowAllButPinnedVerifier)
            .followRedirects(false) // §17.8 spirit: never bounce a pinned identity elsewhere
            .followSslRedirects(false)
            .retryOnConnectionFailure(false)
            .connectTimeout(connectTimeoutMs, TimeUnit.MILLISECONDS)
            .callTimeout(callTimeoutMs, TimeUnit.MILLISECONDS)
            .readTimeout(readTimeoutMs, TimeUnit.MILLISECONDS)
            .writeTimeout(30_000, TimeUnit.MILLISECONDS)
            .build()
    }

    /** §17.3 pin = SHA-256 over the DER SubjectPublicKeyInfo of the leaf certificate. */
    fun pinOf(leaf: X509Certificate): String {
        val digest = MessageDigest.getInstance("SHA-256").digest(leaf.publicKey.encoded)
        return B64Url.encode(digest)
    }

    /** Error classification shared with [SseStream]. */
    fun classifyNetworkError(e: Throwable, pinMismatch: Boolean): MeshCoreException = when {
        e is MeshCoreException -> e
        pinMismatch -> MeshCoreException(
            "PIN_MISMATCH",
            "agent TLS identity differs from pin — terminal, no fallback (CI-12)",
            e,
        )
        e is SSLHandshakeException || e is SSLPeerUnverifiedException ->
            MeshCoreException("TLS_HANDSHAKE_FAILED", "TLS handshake failed", e)
        e is SSLException ->
            MeshCoreException("TLS_HANDSHAKE_FAILED", "TLS error", e)
        e is InterruptedIOException ->
            MeshCoreException("TIMEOUT", "request timed out", e) // [DESIGN] code
        e is IOException ->
            MeshCoreException("NETWORK_ERROR", "network error", e) // [DESIGN] code
        else ->
            MeshCoreException("UNKNOWN", "unexpected error: ${e.javaClass.simpleName}", e)
    }

    fun buildRequest(target: PinnedTarget): Request {
        val builder = Request.Builder().url(target.url)
        for ((name, value) in target.headers) {
            try {
                builder.header(name, value)
            } catch (e: IllegalArgumentException) {
                // Invalid header name/value supplied by the JS layer — drop it rather than fail
                // the whole pinned request; the Agent would reject a malformed request anyway.
            }
        }
        val bodyText = target.bodyJsonText
        if (bodyText != null) {
            builder.method(target.method, bodyText.toRequestBody(JSON_MEDIA.toMediaType()))
        } else {
            builder.method(target.method, null)
        }
        return builder.build()
    }

    // ---------------------------------------------------------------- body / json helpers

    private fun readBounded(response: Response): String {
        val source = response.body?.source() ?: return ""
        val buffer = okio.Buffer()
        while (buffer.size <= MAX_BODY_BYTES) {
            if (source.read(buffer, 16L * 1024L) == -1L) break
        }
        if (buffer.size > MAX_BODY_BYTES) {
            throw MeshCoreException("BODY_TOO_LARGE", "response body exceeds the $MAX_BODY_BYTES byte cap") // [DESIGN]
        }
        return buffer.readUtf8()
    }

    /** Returns parsed JSON (Map/List/primitives) or null for non-JSON bodies. Errors from a hostile server never crash the app. */
    fun parseJsonOrNull(text: String): Any? {
        if (text.isBlank()) return null
        val trimmed = text.trim()
        return try {
            when {
                trimmed.startsWith("{") -> jsonToKotlin(JSONObject(trimmed))
                trimmed.startsWith("[") -> jsonToKotlin(JSONArray(trimmed))
                else -> null
            }
        } catch (e: JSONException) {
            null
        }
    }

    fun jsonToKotlin(value: Any?): Any? = when (value) {
        null, JSONObject.NULL -> null
        is JSONObject -> {
            val map = LinkedHashMap<String, Any?>()
            val keys = value.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                map[key] = jsonToKotlin(value.opt(key))
            }
            map
        }
        is JSONArray -> {
            val list = ArrayList<Any?>(value.length())
            for (i in 0 until value.length()) {
                list.add(jsonToKotlin(value.opt(i)))
            }
            list
        }
        else -> value
    }

    // ---------------------------------------------------------------- TLS plumbing

    /**
     * §17.3 pin-only trust manager. `mismatch` lets the caller distinguish PIN_MISMATCH from a
     * generic TLS handshake failure after JSSE wraps our CertificateException.
     */
    class PinningTrustManager(private val pinSha256: ByteArray) : X509TrustManager {

        val mismatch = AtomicBoolean(false)

        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {
            // §17.3: no mTLS in v1 — the device authenticates with its keystore-signed challenge,
            // not a client certificate.
            throw CertificateException("client certificates are not used in v1")
        }

        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {
            if (chain.isEmpty()) throw CertificateException("empty server chain")
            val leaf = chain[0]
            // §17.3: leaf.publicKey.encoded IS the DER-encoded SubjectPublicKeyInfo.
            val digest = MessageDigest.getInstance("SHA-256").digest(leaf.publicKey.encoded)
            // Constant-time compare (§17.3 "never compare secrets with ==").
            if (!MessageDigest.isEqual(digest, pinSha256)) {
                mismatch.set(true)
                throw CertificateException("SPKI pin mismatch")
            }
            try {
                leaf.checkValidity()
            } catch (e: CertificateExpiredException) {
                throw CertificateException("agent certificate is expired")
            } catch (e: CertificateNotYetValidException) {
                throw CertificateException("agent certificate is not yet valid")
            }
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = arrayOf()
    }

    /** Verifier placeholder — the real check happened in [PinningTrustManager]; see buildPinnedClient for why. */
    private object AllowAllButPinnedVerifier : HostnameVerifier {
        override fun verify(hostname: String?, session: javax.net.ssl.SSLSession?): Boolean = true
    }

    /** Belt-and-braces TLS 1.3 enforcement at the socket layer, on top of the ConnectionSpec. */
    class Tls13OnlySocketFactory(private val delegate: SSLSocketFactory) : SSLSocketFactory() {

        private fun harden(socket: Socket): Socket {
            if (socket is SSLSocket) {
                socket.enabledProtocols = arrayOf("TLSv1.3") // §17.3; T-22: no downgrade
            }
            return socket
        }

        override fun getDefaultCipherSuites(): Array<String> = delegate.defaultCipherSuites
        override fun getSupportedCipherSuites(): Array<String> = delegate.supportedCipherSuites

        override fun createSocket(socket: Socket, host: String, port: Int, autoClose: Boolean): Socket =
            harden(delegate.createSocket(socket, host, port, autoClose))

        override fun createSocket(host: String, port: Int): Socket =
            harden(delegate.createSocket(host, port))

        override fun createSocket(host: String, port: Int, localHost: InetAddress, localPort: Int): Socket =
            harden(delegate.createSocket(host, port, localHost, localPort))

        override fun createSocket(host: InetAddress, port: Int): Socket =
            harden(delegate.createSocket(host, port))

        override fun createSocket(address: InetAddress, port: Int, localAddress: InetAddress, localPort: Int): Socket =
            harden(delegate.createSocket(address, port, localAddress, localPort))
    }
}
