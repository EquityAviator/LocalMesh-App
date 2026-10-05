package ai.localmesh.meshcore

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.Executors
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit

/**
 * WP-11/12 instrumented tests — NSD discovery against a locally advertised
 * `_localmesh._tcp.` service (§16.2 TXT contract):
 *   v=1, aid=<agent_id>, n=<display_name>, fp=<first 16 of pin>, api=v1, po=0|1
 *
 * Runs on a device/emulator: `./gradlew :mesh-core:connectedDebugAndroidTest`.
 * Exercises the SAME NsdManager APIs the App relies on, including the
 * `registerServiceInfoCallback` resolve path (§6.4; the FLAG_SHOW_PICKER
 * permission-free A17 path is exercised manually in the permission lab).
 */
@RunWith(AndroidJUnit4::class)
class NsdInstrumentedTest {

    private val context: Context = ApplicationProvider.getApplicationContext()

    private data class Found(
        val aid: String,
        val name: String,
        val fp: String,
        val api: String,
        val po: String,
        val addresses: List<String>,
        val port: Int,
    )

    private fun newDiscovery(events: LinkedBlockingQueue<Pair<String, Map<String, Any?>>>): NsdDiscovery =
        NsdDiscovery(
            context,
            emit = { name, payload -> events.add(name to payload) },
            resolveExecutor = Executors.newSingleThreadExecutor(),
        )

    @Test
    fun normalizeServiceType_acceptsSpecVariants_andRejectsEverythingElse() {
        val d = newDiscovery(LinkedBlockingQueue())
        assertEquals("_localmesh._tcp", d.normalizeServiceType("_localmesh._tcp"))
        assertEquals("_localmesh._tcp", d.normalizeServiceType("localmesh"))
        assertEquals("_localmesh._tcp", d.normalizeServiceType("_localmesh._tcp.local."))
        try {
            d.normalizeServiceType("_googlecast._tcp")
            fail("foreign service types must fail with NSD_ERROR (§16.2 defines exactly one type in v1)")
        } catch (e: MeshCoreException) {
            assertEquals("NSD_ERROR", e.code)
        }
    }

    @Test
    fun discovery_findsAdvertisedAgent_andParsesTxtPerSpec162() {
        val events = LinkedBlockingQueue<Pair<String, Map<String, Any?>>>()
        val discovery = newDiscovery(events)

        // Advertise a fake Agent with the §16.2 TXT keys.
        val nsdManager = context.getSystemService(Context.NSD_SERVICE) as NsdManager
        val info = NsdServiceInfo().apply {
            serviceName = "meta (111111)"
            serviceType = "_localmesh._tcp."
            port = 8443
            setAttribute("v", "1")
            setAttribute("aid", "11111111-2222-3333-4444-555555555555")
            setAttribute("n", "meta")
            setAttribute("fp", "aBcDeFgHiJkLmNoP") // first 16 of pin — hint only (§16.2)
            setAttribute("api", "v1")
            setAttribute("po", "0")
        }
        var listener: NsdManager.RegistrationListener? = null

        try {
            listener = object : NsdManager.RegistrationListener {
                override fun onServiceRegistered(s: NsdServiceInfo) {}
                override fun onRegistrationFailed(s: NsdServiceInfo, e: Int) {}
                override fun onServiceUnregistered(s: NsdServiceInfo) {}
                override fun onUnregistrationFailed(s: NsdServiceInfo, e: Int) {}
            }
            nsdManager.registerService(info, NsdManager.PROTOCOL_DNS_SD, listener)

            // start() reports success asynchronously via onStarted(null).
            val started = LinkedBlockingQueue<MeshCoreException?>()
            discovery.start("_localmesh._tcp.") { started.add(it) }
            assertEquals(null, started.poll(10, TimeUnit.SECONDS))

            // §18.8: "Same Wi-Fi, mDNS on → discovery" — allow generous CI time.
            val deadline = System.currentTimeMillis() + 30_000
            var found: Found? = null
            while (System.currentTimeMillis() < deadline && found == null) {
                val evt = events.poll(1, TimeUnit.SECONDS) ?: continue
                if (evt.first == "agentFound") {
                    val p = evt.second
                    found = Found(
                        aid = p["aid"] as String,
                        name = p["name"] as String,
                        fp = (p["fp"] as? String) ?: "",
                        api = (p["api"] as? String) ?: "",
                        po = (p["po"] as? String) ?: "",
                        addresses = (p["addresses"] as? List<String>) ?: emptyList(),
                        port = (p["port"] as? Int) ?: (p["port"] as? Long)?.toInt() ?: 0,
                    )
                }
            }
            assertNotNull("agentFound not seen within 30 s", found)
            val f = found!!
            assertEquals("11111111-2222-3333-4444-555555555555", f.aid)
            assertEquals("v1", f.api)
            assertEquals("0", f.po)
            assertTrue("fp hint must be surfaced", f.fp.isNotEmpty())
            assertTrue("at least one IPv4 address surfaced (v1 is IPv4-only)", f.addresses.isNotEmpty())
            assertEquals(8443, f.port)
        } finally {
            discovery.stop()
            listener?.let { nsdManager.unregisterService(it) }
        }
    }
}
