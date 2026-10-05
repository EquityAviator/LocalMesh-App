package ai.localmesh.meshcore

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import expo.modules.interfaces.permissions.PermissionsResponseListener
import expo.modules.interfaces.permissions.PermissionsStatus
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

// MeshCore — Expo native module implementing the §11.2 normative TypeScript contract
// (LM-ARCH-001). Registered via expo-module.config.json as "MeshCore".
//
// §11.2 surface exposed here (promise-based, JS wrapper owned by Task 2-b):
//   createDeviceKey(alias) / signWithDeviceKey(alias, dataB64Url) / deleteDeviceKey(alias)
//   request(req) / openStream(req) / cancelStream(streamId)  [cancelStream = StreamHandle.cancel()]
//   startDiscovery(serviceType) / stopDiscovery()
//   getNetworkState() / getLocalNetworkPermission() / requestLocalNetworkPermission()
//   isPackageInstalled(pkg)
//
// Events: 'agentFound' {aid,name,fp,api,po,addresses,port}
//         'agentLost'  {aid}
//         'networkChanged' {transport,vpnActive,metered}
//         'streamEvent' {streamId, kind:'event'|'error'|'closed', event?,data?,code?,message?,reason?}
//           — per-handle StreamHandle events are multiplexed on 'streamEvent' because the Expo
//             bridge has no per-object emitters; Task 2-b demuxes by streamId.
//
// §17.6: the device private key NEVER crosses this bridge — only create/sign/delete exist; there
// is no export function and no function returns key material other than the PUBLIC SPKI.
//
// §17.10: no logging anywhere in this module (deny-by-default posture); error messages never
// contain pins beyond a 12-char diagnostic prefix, tokens, or body content.
class MeshCoreModule : Module() {

    private val mainHandler = Handler(Looper.getMainLooper())
    private val io: ExecutorService = Executors.newCachedThreadPool { runnable ->
        Thread(runnable, "mesh-core-io").apply { isDaemon = true }
    }
    private val streams = ConcurrentHashMap<String, SseStream>()
    private var nsd: NsdDiscovery? = null
    private var netMonitor: NetMonitor? = null

    override fun definition() = ModuleDefinition {
        Name("MeshCore")

        Events(
            "agentFound",
            "agentLost",
            "networkChanged",
            "streamEvent",
        )

        OnCreate {
            val context = appContext?.reactContext
            if (context != null) {
                // NSD object creation must happen on a Looper thread; OnCreate runs on main.
                nsd = NsdDiscovery(context, ::emitOnMain, io)
                netMonitor = NetMonitor(context, mainHandler, ::emitOnMain).also { it.start() }
            }
        }

        OnDestroy {
            netMonitor?.stop()
            nsd?.stop()
            for (stream in streams.values) stream.cancel()
            streams.clear()
            io.shutdown()
        }

        // ------------------------------------------------ keys (§11.2 keys; §17.3; §17.6)

        Function("createDeviceKey") { alias: String, promise: Promise ->
            io.execute {
                try {
                    val info = DeviceKeys.createDeviceKey(alias)
                    promise.resolve(
                        mapOf(
                            "publicKeySpkiB64Url" to info.publicKeySpkiB64Url,
                            "hardwareBacked" to info.hardwareBacked,
                        )
                    )
                } catch (e: MeshCoreException) {
                    promise.reject(e.code, e.message, e)
                } catch (e: Exception) {
                    // §17.10: class name only — never the exception text, which could echo arguments.
                    promise.reject("KEYSTORE_ERROR", "createDeviceKey failed: ${e.javaClass.simpleName}", e)
                }
            }
        }

        Function("signWithDeviceKey") { alias: String, dataB64Url: String, promise: Promise ->
            io.execute {
                try {
                    promise.resolve(DeviceKeys.signWithDeviceKey(alias, dataB64Url))
                } catch (e: MeshCoreException) {
                    promise.reject(e.code, e.message, e)
                } catch (e: Exception) {
                    promise.reject("KEYSTORE_ERROR", "signWithDeviceKey failed: ${e.javaClass.simpleName}", e)
                }
            }
        }

        Function("deleteDeviceKey") { alias: String, promise: Promise ->
            io.execute {
                try {
                    DeviceKeys.deleteDeviceKey(alias)
                    promise.resolve(null)
                } catch (e: MeshCoreException) {
                    promise.reject(e.code, e.message, e)
                } catch (e: Exception) {
                    promise.reject("KEYSTORE_ERROR", "deleteDeviceKey failed: ${e.javaClass.simpleName}", e)
                }
            }
        }

        // ------------------------------------------------ pinned HTTP (§11.2 request)

        Function("request") { req: Map<String, Any?>?, promise: Promise ->
            io.execute {
                try {
                    val body = req ?: emptyMap()
                    val result = PinnedHttp.request(body, BuildConfig.DEBUG) // §17.9 carve-out flag
                    promise.resolve(
                        mapOf(
                            "status" to result.status,
                            "headers" to result.headers,
                            "bodyJson" to result.bodyJson,
                            "tlsSpkiSha256B64Url" to result.tlsSpkiSha256B64Url,
                        )
                    )
                } catch (e: MeshCoreException) {
                    promise.reject(e.code, e.message, e)
                } catch (e: Exception) {
                    promise.reject("NETWORK_ERROR", "request failed: ${e.javaClass.simpleName}", e)
                }
            }
        }

        // ------------------------------------------------ pinned SSE (§11.2 openStream)

        // Resolves { streamId } once response headers arrive; frames arrive as 'streamEvent'.
        Function("openStream") { req: Map<String, Any?>?, promise: Promise ->
            val body = req ?: emptyMap()
            val stream = SseStream(BuildConfig.DEBUG) { payload -> onStreamPayload(payload) }
            streams[stream.id] = stream
            io.execute {
                stream.open(body) { openError ->
                    if (openError == null) {
                        promise.resolve(mapOf("streamId" to stream.id))
                    } else {
                        streams.remove(stream.id)
                        promise.reject(openError.code, openError.message, openError)
                    }
                }
            }
        }

        // StreamHandle.cancel() (§11.2) — closes the socket; the Agent cancels upstream (§13.7).
        Function("cancelStream") { streamId: String, promise: Promise ->
            val stream = streams.remove(streamId)
            stream?.cancel()
            promise.resolve(null)
        }

        // ------------------------------------------------ discovery (§11.2; §16.2; §6.4)

        Function("startDiscovery") { serviceType: String, promise: Promise ->
            val discovery = nsd
            if (discovery == null) {
                promise.reject("NSD_ERROR", "module not initialized", null)
            } else {
                mainHandler.post {
                    discovery.start(serviceType) { error ->
                        if (error == null) {
                            promise.resolve(null)
                        } else {
                            promise.reject(error.code, error.message, error)
                        }
                    }
                }
            }
        }

        Function("stopDiscovery") { promise: Promise ->
            val discovery = nsd
            if (discovery != null) {
                mainHandler.post { discovery.stop() }
            }
            promise.resolve(null)
        }

        // ------------------------------------------------ network (§11.2; §6.4)

        Function("getNetworkState") { promise: Promise ->
            val state = netMonitor?.currentState()
                ?: mapOf("transport" to "none", "vpnActive" to false, "metered" to false)
            promise.resolve(state)
        }

        // ------------------------------------------------ permissions (§6.4)

        Function("getLocalNetworkPermission") { promise: Promise ->
            val context = appContext?.reactContext
            if (context == null) {
                promise.reject("PERMISSION_REQUIRED", "no application context", null)
            } else {
                promise.resolve(LocalNetworkPermissions.getLocalNetworkPermission(context))
            }
        }

        Function("requestLocalNetworkPermission") { promise: Promise ->
            val context = appContext?.reactContext
            if (context == null) {
                promise.reject("PERMISSION_REQUIRED", "no application context", null)
                return@Function
            }
            // §6.4: never request ACCESS_LOCAL_NETWORK before targetSdk 37 — resolve immediately;
            // the JS layer treats the implicit/not_required state as usable access.
            if (!LocalNetworkPermissions.needsRuntimeRequest(context)) {
                promise.resolve("granted")
                return@Function
            }
            val permissions = appContext?.permissions
            if (permissions == null) {
                promise.reject("PERMISSION_REQUIRED", "permissions API unavailable", null)
                return@Function
            }
            permissions.askForPermissions(
                PermissionsResponseListener { result ->
                    val response = result[LocalNetworkPermissions.ACCESS_LOCAL_NETWORK]
                    promise.resolve(
                        if (response?.status == PermissionsStatus.GRANTED) "granted" else "denied"
                    )
                },
                LocalNetworkPermissions.ACCESS_LOCAL_NETWORK,
            )
        }

        // §11.2: "used for Tailscale hint only" — allow-listed in LocalNetworkPermissions.
        Function("isPackageInstalled") { pkg: String, promise: Promise ->
            val context = appContext?.reactContext
            if (context == null) {
                promise.reject("PERMISSION_REQUIRED", "no application context", null)
            } else {
                promise.resolve(LocalNetworkPermissions.isPackageInstalled(context, pkg))
            }
        }
    }

    // ---------------------------------------------------------------- event plumbing

    private fun onStreamPayload(payload: Map<String, Any?>) {
        if (payload["kind"] == "closed") {
            val streamId = payload["streamId"]
            if (streamId is String) streams.remove(streamId)
        }
        emitOnMain("streamEvent", payload)
    }

    /** All events are posted on the main dispatcher (§ backpressure rule: producers never touch the UI thread directly). */
    private fun emitOnMain(name: String, payload: Map<String, Any?>) {
        mainHandler.post { sendEvent(name, payload.toBundle()) }
    }

    private fun Map<String, Any?>.toBundle(): Bundle {
        val bundle = Bundle()
        for ((key, value) in this) {
            when (value) {
                null -> bundle.putString(key, null)
                is String -> bundle.putString(key, value)
                is Int -> bundle.putInt(key, value)
                is Long -> bundle.putLong(key, value)
                is Boolean -> bundle.putBoolean(key, value)
                is List<*> -> {
                    val list = ArrayList<String>()
                    for (item in value) {
                        if (item != null) list.add(item.toString())
                    }
                    bundle.putStringArrayList(key, list)
                }
                else -> bundle.putString(key, value.toString())
            }
        }
        return bundle
    }
}
