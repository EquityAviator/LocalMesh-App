package ai.localmesh.meshcore

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.os.Handler
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

// §11.2 getNetworkState() + 'networkChanged' event.
//
// State model (§11.2): { transport: 'wifi'|'cellular'|'ethernet'|'none', vpnActive: boolean,
// metered: boolean }.
//
// §6.4 consequence: local-network access is a first-class connection-failure cause (CI-09); the
// Connection Manager (JS, Task 2-b) models permission state and uses these signals for the
// §15.x re-race triggers (NETWORK_CHANGED) and backoff reset.
//
// VPN: Tailscale on Android is a VPN (§6.3). A VPN network's NetworkCapabilities carry the
// underlying transports as well, so `transport` stays meaningful (e.g. 'wifi' under Tailscale);
// `vpnActive` is tracked by listening for TRANSPORT_VPN networks explicitly (§6.3 "one active VPN").
class NetMonitor(
    context: Context,
    private val mainHandler: Handler,
    private val emit: (name: String, payload: Map<String, Any?>) -> Unit,
) {
    private val connectivity =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    private val started = AtomicBoolean(false)
    private val vpnTunnels = AtomicInteger(0)
    private var defaultCallback: ConnectivityManager.NetworkCallback? = null
    private var vpnCallback: ConnectivityManager.NetworkCallback? = null

    fun start() {
        if (!started.compareAndSet(false, true)) return

        val defaultCb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) = notifyChanged()
            override fun onLost(network: Network) = notifyChanged()
            override fun onCapabilitiesChanged(network: Network, networkCapabilities: NetworkCapabilities) =
                notifyChanged()

            // §6.4: a network-level block (e.g. local-network permission) is a first-class failure
            // cause — surface it as a networkChanged so the JS state machine can re-race (CI-09).
            override fun onBlockedStatusChanged(network: Network, blocked: Boolean) = notifyChanged()
        }
        connectivity.registerDefaultNetworkCallback(defaultCb, mainHandler)
        defaultCallback = defaultCb

        val vpnCb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                vpnTunnels.incrementAndGet()
                notifyChanged()
            }

            override fun onLost(network: Network) {
                vpnTunnels.decrementAndGet()
                notifyChanged()
            }
        }
        val vpnRequest = NetworkRequest.Builder()
            .addTransportType(NetworkCapabilities.TRANSPORT_VPN)
            .removeCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN) // default requests exclude VPNs
            .build()
        connectivity.registerNetworkCallback(vpnRequest, vpnCb, mainHandler)
        vpnCallback = vpnCb

        notifyChanged() // seed the callback map with the current state
    }

    fun stop() {
        defaultCallback?.let { runCatching { connectivity.unregisterNetworkCallback(it) } }
        vpnCallback?.let { runCatching { connectivity.unregisterNetworkCallback(it) } }
        defaultCallback = null
        vpnCallback = null
        started.set(false)
    }

    /** §11.2 getNetworkState(). Cheap enough to call synchronously from the bridge. */
    fun currentState(): Map<String, Any?> {
        val network = connectivity.activeNetwork
        val caps = network?.let { connectivity.getNetworkCapabilities(it) }
        // §11.2 transport precedence under a VPN: wifi > ethernet > cellular among the (possibly
        // underlying) transports of the active network.
        val transport = when {
            caps == null -> "none"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            else -> "none"
        }
        val metered = caps != null && !caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)
        val vpnActive = vpnTunnels.get() > 0 ||
            (caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) ?: false)
        return mapOf(
            "transport" to transport,
            "vpnActive" to vpnActive,
            "metered" to metered,
        )
    }

    private fun notifyChanged() {
        // Callbacks are registered with mainHandler, so this is already on the main dispatcher;
        // the module's emit wrapper posts again — harmless and keeps every emit path main-bound.
        emit("networkChanged", currentState())
    }
}
