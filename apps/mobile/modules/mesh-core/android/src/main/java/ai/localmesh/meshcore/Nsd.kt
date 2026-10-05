package ai.localmesh.meshcore

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Build
import java.net.Inet4Address
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executor
import java.util.concurrent.atomic.AtomicBoolean

// §16.2 mDNS advertisement discovery + §6.4 system-mediated resolution.
//
// §16.2 (what the App discovers): service type `_localmesh._tcp.local.`, TXT keys
//   v=1, aid=<agent_id>, n=<display_name>, fp=<first 16 chars of b64url(SPKI sha256)> (hint only),
//   api=v1, po=0|1 — each entry ≤ 255 bytes. Records with v≠1 are ignored.
// §17.3/T-21: advertisements are untrusted hints; identity = TLS pin + agent_id match. `fp` and
//   `n` are therefore passed through verbatim, never trusted.
// §16.2: IPv4 only in v1 — IPv6 addresses are filtered out.
//
// §6.4 resolution path: `registerServiceInfoCallback` (API 34+) supersedes deprecated
// `resolveService`; on Android 17 the NsdManager system picker (DiscoveryRequest.FLAG_SHOW_PICKER)
// provides a permission-free resolve path — see the comment in resolve() and the README.
class NsdDiscovery(
    context: Context,
    private val emit: (name: String, payload: Map<String, Any?>) -> Unit,
    private val resolveExecutor: Executor,
) {
    private val nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager

    private val discovering = AtomicBoolean(false)
    private var discoveryListener: NsdManager.DiscoveryListener? = null
    private val aidByServiceName = ConcurrentHashMap<String, String>()
    private val infoCallbacks = ConcurrentHashMap<String, NsdManager.ServiceInfoCallback>()

    /**
     * §16.2 defines exactly one service type in v1; variants ("localmesh", "_localmesh._tcp",
     * "_localmesh._tcp.local", trailing dots) are normalized, everything else fails with NSD_ERROR.
     */
    fun normalizeServiceType(raw: String): String {
        val trimmed = raw.trim().trimEnd('.')
        val withUnderscore = if (trimmed.startsWith("_")) trimmed else "_$trimmed"
        val withoutScope = if (withUnderscore.endsWith(".local")) {
            withUnderscore.removeSuffix(".local")
        } else {
            withUnderscore
        }
        if (withoutScope != SERVICE_TYPE_V1) {
            throw MeshCoreException("NSD_ERROR", "only $SERVICE_TYPE_V1 is defined in v1 (§16.2)")
        }
        return SERVICE_TYPE_V1
    }

    /** Starts discovery. [onStarted] fires exactly once with null on success or the failure. */
    fun start(rawServiceType: String, onStarted: (MeshCoreException?) -> Unit) {
        if (!discovering.compareAndSet(false, true)) {
            onStarted(null) // idempotent: already discovering (§11.2 startDiscovery → void)
            return
        }
        val serviceType = try {
            normalizeServiceType(rawServiceType)
        } catch (e: MeshCoreException) {
            discovering.set(false)
            onStarted(e)
            return
        }
        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(regType: String) {
                onStarted(null)
            }

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                discovering.set(false)
                onStarted(MeshCoreException("NSD_ERROR", "startDiscovery failed (nsd code $errorCode)"))
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                resolve(serviceInfo)
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                val aid = aidByServiceName.remove(serviceInfo.serviceName) ?: serviceInfo.serviceName
                emit("agentLost", mapOf("aid" to aid))
            }

            override fun onDiscoveryStopped(serviceType: String) {
                // clean stop — no event in the §11.2 contract
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                // listener is already considered stopped by NsdManager; nothing further to do
            }
        }
        discoveryListener = listener
        try {
            nsdManager.discoverServices(serviceType, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (e: Exception) {
            discovering.set(false)
            discoveryListener = null
            onStarted(MeshCoreException("NSD_ERROR", "discoverServices rejected: ${e.javaClass.simpleName}", e))
        }
    }

    /** Clean unregister of every callback and the discovery session (§11.2 stopDiscovery). Idempotent. */
    fun stop() {
        if (Build.VERSION.SDK_INT >= 34) {
            for (callback in infoCallbacks.values) {
                try {
                    nsdManager.unregisterServiceInfoCallback(callback)
                } catch (e: Exception) {
                    // already unregistered by the system — fine
                }
            }
        }
        infoCallbacks.clear()
        val listener = discoveryListener
        if (discovering.compareAndSet(true, false) && listener != null) {
            try {
                nsdManager.stopServiceDiscovery(listener)
            } catch (e: Exception) {
                // stop is best-effort; the session is dropped either way
            }
        }
        discoveryListener = null
        aidByServiceName.clear()
    }

    // ---------------------------------------------------------------- resolution

    private fun resolve(info: NsdServiceInfo) {
        if (Build.VERSION.SDK_INT >= 34) {
            // §6.4: registerServiceInfoCallback supersedes the deprecated resolveService on API 34+.
            //
            // §6.4 (Android 17): NsdManager also offers a system-mediated picker usable WITHOUT the
            // ACCESS_LOCAL_NETWORK permission — `NsdManager.DiscoveryRequest.Builder()
            // .setFlag(NsdManager.DiscoveryRequest.FLAG_SHOW_PICKER)` handed to
            // registerServiceInfoCallback. It is intentionally NOT enabled in v1: it surfaces a
            // system dialog per resolution and the §11.2 contract models permission state through
            // getLocalNetworkPermission()/requestLocalNetworkPermission() instead. Adopting the
            // picker is a one-function change behind a compileSdk-37 build — recorded in README
            // "Deferred: FLAG_SHOW_PICKER path".
            val callback = object : NsdManager.ServiceInfoCallback {
                override fun onServiceUpdated(serviceInfo: NsdServiceInfo) {
                    handleResolved(serviceInfo)
                }

                override fun onServiceInfoCallbackRegistrationFailed(errorCode: Int) {
                    // Keep discovery alive; this single service is skipped (robustness over
                    // strictness — one malformed advert must not kill the session).
                }

                override fun onServiceLost() {
                    val aid = aidByServiceName.remove(info.serviceName) ?: info.serviceName
                    emit("agentLost", mapOf("aid" to aid))
                }

                override fun onServiceInfoCallbackUnregistered() {
                    infoCallbacks.remove(info.serviceName)
                }
            }
            infoCallbacks[info.serviceName] = callback
            try {
                nsdManager.registerServiceInfoCallback(info, resolveExecutor, callback)
            } catch (e: Exception) {
                infoCallbacks.remove(info.serviceName)
            }
        } else {
            @Suppress("DEPRECATION")
            nsdManager.resolveService(
                info,
                object : NsdManager.ResolveListener {
                    override fun onResolveFailed(info: NsdServiceInfo, errorCode: Int) {
                        // skip this service; discovery continues
                    }

                    override fun onServiceResolved(info: NsdServiceInfo) {
                        handleResolved(info)
                    }
                },
            )
        }
    }

    private fun handleResolved(info: NsdServiceInfo) {
        val attrs = LinkedHashMap<String, String>()
        for ((key, value) in info.attributes) {
            // §16.2: each TXT entry ≤ 255 bytes; oversized or empty values are ignored, not fatal.
            if (value == null || value.isEmpty() || value.size > 255) continue
            attrs[key] = String(value, Charsets.UTF_8)
        }
        val v = attrs["v"] ?: return // §16.2: records without v are ignored
        if (v != "1") return // §16.2: ignore v≠1
        val aid = attrs["aid"] ?: return // unidentifiable advertisement (T-21) — never emit
        aidByServiceName[info.serviceName] = aid

        emit(
            "agentFound",
            mapOf(
                "aid" to aid,
                "name" to (attrs["n"] ?: info.serviceName),
                // §16.2: fp is a 16-char hint only; the full pin is verified by TLS (§17.3).
                "fp" to (attrs["fp"] ?: ""),
                "api" to (attrs["api"] ?: ""),
                "po" to (attrs["po"] ?: ""),
                "addresses" to ipv4AddressesOf(info),
                "port" to info.port,
            ),
        )
    }

    /** §16.2: IPv4 only in v1 — IPv6 addresses are dropped. */
    private fun ipv4AddressesOf(info: NsdServiceInfo): List<String> =
        if (Build.VERSION.SDK_INT >= 34) {
            info.hostAddresses
                .filterIsInstance<Inet4Address>()
                .mapNotNull { it.hostAddress }
        } else {
            val single = info.hostAddress
            if (single != null && !single.contains(':')) listOf(single) else emptyList()
        }

    private companion object {
        const val SERVICE_TYPE_V1 = "_localmesh._tcp"
    }
}
