package ai.localmesh.meshcore

import java.io.IOException
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import okhttp3.Call
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okio.BufferedSource

// §11.2 pinned SSE — openStream per the normative contract:
//   openStream(req: { url; method 'POST'; headers?; bodyJson; pinSpkiSha256B64Url; idleTimeoutMs })
//     → StreamHandle with events 'event' {event?, data}, 'error' {code, message}, 'closed' {reason}
//   StreamHandle.cancel() closes the socket (the Agent sees the disconnect and cancels upstream).
//
// Expo's bridge cannot return an object with methods/events, so the native surface is:
//   - openStream resolves { streamId } once response HEADERS arrive (failures reject the promise);
//   - all stream frames are multiplexed on the module 'streamEvent' event as
//     { streamId, kind: 'event'|'error'|'closed', event?, data?, code?, message?, reason? };
//   - handle.cancel() maps to the cancelStream(streamId) native function.
// Task 2-b demuxes by streamId to implement the per-handle EventEmitter. See README mapping table.
//
// §11.2 rule: the pin is mandatory here too — resolveTarget fails closed with PIN_REQUIRED before
// any socket is opened. §17.3: TLS 1.3 only, pin-only trust (identical plumbing to PinnedHttp).
//
// SSE parsing: multi-line `data:` frames, CRLF/LF, `data:`/`event:` prefixes with one optional
// leading space, `:`-comment frames (Agent keep-alive pings, §13.7) which still reset the idle
// watchdog, and [DONE] passed through verbatim (the JS layer owns the semantics).
class SseStream(
    private val allowDebugCleartext: Boolean,
    private val emit: (payload: Map<String, Any?>) -> Unit,
) {
    val id: String = UUID.randomUUID().toString()

    private val cancelled = AtomicBoolean(false)
    private val terminalSent = AtomicBoolean(false)
    private val openReplied = AtomicBoolean(false)
    private val opened = AtomicBoolean(false)
    private val lastActivityNanos = AtomicReference(System.nanoTime())
    private var call: Call? = null
    private var watchdog: ScheduledExecutorService? = null

    /**
     * Blocking open + read loop. Run on a worker thread (MeshCoreModule and the instrumented
     * tests do). [onOpened] fires exactly once: null when response headers arrived (2xx),
     * otherwise the failure — which is also the openStream promise rejection.
     */
    fun open(req: Map<String, Any?>, onOpened: (MeshCoreException?) -> Unit) {
        if (!opened.compareAndSet(false, true)) {
            replyOpened(onOpened, MeshCoreException("INVALID_REQUEST", "stream already opened"))
            return
        }
        val target = try {
            PinnedHttp.resolveTarget(req, allowDebugCleartext, requireBody = true, requireTimeoutMs = false)
        } catch (e: MeshCoreException) {
            replyOpened(onOpened, e)
            return
        }
        if (target.method != "POST") {
            // §11.2: openStream req.method is typed 'POST'.
            replyOpened(onOpened, MeshCoreException("INVALID_REQUEST", "openStream method must be POST (§11.2)"))
            return
        }
        val bodyText = target.bodyJsonText ?: "{}"

        // Watchdog owns IDLE_TIMEOUT; socket read timeout is a backstop slightly beyond it so the
        // watchdog's typed error always wins the race.
        val trustManager = PinnedHttp.PinningTrustManager(target.pinBytes)
        val client = PinnedHttp.buildPinnedClient(
            trustManager,
            allowDebugCleartext,
            connectTimeoutMs = target.timeoutMs.takeIf { it > 0L } ?: 10_000L,
            callTimeoutMs = 0L, // streams are unbounded by design; idleTimeoutMs governs liveness
            readTimeoutMs = target.idleTimeoutMs + 2_000L,
        )
        val request: Request = Request.Builder()
            .url(target.url)
            .apply {
                for ((name, value) in target.headers) {
                    try {
                        header(name, value)
                    } catch (e: IllegalArgumentException) {
                        // drop malformed header (same policy as PinnedHttp.buildRequest)
                    }
                }
                // §11.2: pinned POST SSE — body is required (Agent streams are POST bodies).
                post(bodyText.toRequestBody("application/json; charset=utf-8".toMediaType()))
            }
            .build()

        val newCall = client.newCall(request)
        call = newCall
        startWatchdog(target.idleTimeoutMs)
        try {
            newCall.execute().use { response ->
                if (!response.isSuccessful) {
                    // §17.10: never echo the response body into the error message.
                    replyOpened(onOpened, MeshCoreException("HTTP_ERROR", "agent returned status ${response.code} for stream open")) // [DESIGN] code
                    return
                }
                replyOpened(onOpened, null)
                val source = response.body?.source()
                if (source == null) {
                    emitClosed("eof")
                    return
                }
                parseLoop(source)
                emitClosed("eof")
            }
        } catch (e: Throwable) {
            if (openReplied.get()) {
                if (!terminalSent.get()) {
                    if (cancelled.get()) {
                        emitClosed("cancelled")
                    } else {
                        emitError(PinnedHttp.classifyNetworkError(e, trustManager.mismatch.get()))
                        emitClosed("io-error")
                    }
                }
            } else {
                replyOpened(onOpened, PinnedHttp.classifyNetworkError(e, trustManager.mismatch.get()))
            }
        } finally {
            shutdownWatchdog()
        }
    }

    /** §11.2 StreamHandle.cancel() — closes the socket; Agent cancels upstream on disconnect (§13.7). */
    fun cancel() {
        if (cancelled.compareAndSet(false, true)) {
            call?.cancel()
        }
    }

    // ---------------------------------------------------------------- internals

    private fun parseLoop(source: BufferedSource) {
        var eventName: String? = null
        val data = StringBuilder()
        while (true) {
            val line = source.readUtf8Line() ?: break // EOF
            // Any bytes — including `:` ping comments (§13.7) and [DONE] — reset the idle watchdog.
            lastActivityNanos.set(System.nanoTime())
            when {
                line.isEmpty() -> {
                    // SSE dispatch boundary: only dispatch frames that carry data (spec behaviour).
                    if (data.isNotEmpty()) {
                        emit(
                            mapOf(
                                "streamId" to id,
                                "kind" to "event",
                                "event" to eventName,
                                "data" to data.toString().removeSuffix("\n"),
                            )
                        )
                        eventName = null
                        data.setLength(0)
                    }
                }
                line.startsWith(":") -> Unit // SSE comment — keep-alive ping (§13.7); watchdog already reset
                line.startsWith("data:") -> data.append(line.substring(5).removePrefix(" ")).append('\n')
                line.startsWith("event:") -> eventName = line.substring(6).removePrefix(" ")
                else -> Unit // id:/retry:/unknown fields — ignored in v1
            }
        }
        // [DONE] frames pass through as ordinary data events; the JS layer owns stream semantics.
    }

    private fun startWatchdog(idleTimeoutMs: Long) {
        val executor = Executors.newSingleThreadScheduledExecutor { runnable ->
            Thread(runnable, "mesh-core-sse-watchdog").apply { isDaemon = true }
        }
        watchdog = executor
        executor.scheduleWithFixedDelay(
            {
                val last = lastActivityNanos.get()
                val idleForNanos = System.nanoTime() - last
                if (idleForNanos >= idleTimeoutMs * 1_000_000L) {
                    // Exactly one terminal path: error then closed, then cancel the socket so the
                    // read loop wakes up and observes terminalSent == true.
                    if (terminalSent.compareAndSet(false, true)) {
                        emit(
                            mapOf(
                                "streamId" to id,
                                "kind" to "error",
                                "code" to "IDLE_TIMEOUT",
                                "message" to "no bytes received within idleTimeoutMs (CI-18)",
                            )
                        )
                        emit(mapOf("streamId" to id, "kind" to "closed", "reason" to "idle-timeout"))
                        call?.cancel()
                    }
                }
            },
            idleTimeoutMs,
            minOf(idleTimeoutMs, 1_000L),
            TimeUnit.MILLISECONDS,
        )
    }

    private fun shutdownWatchdog() {
        watchdog?.shutdownNow()
        watchdog = null
    }

    private fun replyOpened(onOpened: (MeshCoreException?) -> Unit, error: MeshCoreException?) {
        if (openReplied.compareAndSet(false, true)) {
            if (error == null) {
                terminalSent.set(false)
            } else {
                terminalSent.set(true) // never opened → no stream events will follow
            }
            onOpened(error)
        }
    }

    private fun emitError(error: MeshCoreException) {
        if (terminalSent.compareAndSet(false, true)) {
            emit(
                mapOf(
                    "streamId" to id,
                    "kind" to "error",
                    "code" to error.code,
                    "message" to error.message,
                )
            )
            emit(mapOf("streamId" to id, "kind" to "closed", "reason" to "error"))
        }
    }

    private fun emitClosed(reason: String) {
        if (terminalSent.compareAndSet(false, true)) {
            emit(mapOf("streamId" to id, "kind" to "closed", "reason" to reason))
        }
    }
}
