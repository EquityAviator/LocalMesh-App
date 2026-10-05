package ai.localmesh.meshcore

import android.content.Context
import android.content.pm.PackageManager
import android.os.Build

// §6.4 Android platform — local-network permission modelling + package visibility.
//
// §6.4 facts implemented here:
// - Android 16 (API 36): local-network protection is OPT-IN via NEARBY_WIFI_DEVICES.
// - Android 17 (API 37, targetSdk 37): ACCESS_LOCAL_NETWORK is MANDATORY — apps targeting 37+ are
//   blocked from local-network traffic by default and must declare AND request it at runtime.
// - Apps targeting < 37 get an implicit grant when they hold INTERNET.
// - "Do not request ACCESS_LOCAL_NETWORK at runtime before targeting SDK 37."
//
// The four-state mapping ('granted'|'denied'|'not_required'|'unknown') is [DESIGN]: the spec fixes
// the platform rules, not the enum mapping — documented in README "Permissions".
object LocalNetworkPermissions {

    const val ACCESS_LOCAL_NETWORK = "android.permission.ACCESS_LOCAL_NETWORK" // §6.4 (API 37)
    const val NEARBY_WIFI_DEVICES = "android.permission.NEARBY_WIFI_DEVICES"   // §6.4 (API 33+/36)
    const val INTERNET = "android.permission.INTERNET"

    /**
     * Allow-list for isPackageInstalled. §11.2: "used for Tailscale hint only" — the module
     * refuses to answer for any other package so it can never become a package-enumeration
     * oracle (§17.10 spirit); manifest <queries> must stay in sync (see AndroidManifest.xml).
     */
    val ALLOWED_HINT_PACKAGES = setOf("com.tailscale.ipn")

    fun getLocalNetworkPermission(context: Context): String {
        val target = targetSdk(context)
        if (target < 37) {
            // §6.4: implicit grant for targetSdk < 37 when INTERNET is held.
            return if (granted(context, INTERNET)) "not_required" else "denied"
        }
        return when {
            Build.VERSION.SDK_INT >= 37 ->
                when {
                    !declared(context, ACCESS_LOCAL_NETWORK) ->
                        // §6.4: targeting 37 without the declaration can never reach local networks.
                        "denied"
                    granted(context, ACCESS_LOCAL_NETWORK) -> "granted"
                    else -> "denied"
                }
            Build.VERSION.SDK_INT == 36 ->
                // Android 16: opt-in protection (§6.4).
                when {
                    !declared(context, NEARBY_WIFI_DEVICES) -> "not_required"
                    granted(context, NEARBY_WIFI_DEVICES) -> "granted"
                    else -> "denied"
                }
            else ->
                // Pre-Android-16: no local-network protection exists at all.
                "not_required"
        }
    }

    /**
     * §6.4: the runtime request is only ever launched when the app targets 37 AND the device runs
     * 37+. Everything else resolves without a dialog (the JS layer then treats 'not_required' as
     * granted access).
     */
    fun needsRuntimeRequest(context: Context): Boolean =
        targetSdk(context) >= 37 &&
            Build.VERSION.SDK_INT >= 37 &&
            !granted(context, ACCESS_LOCAL_NETWORK)

    fun isPackageInstalled(context: Context, pkg: String): Boolean {
        if (pkg !in ALLOWED_HINT_PACKAGES) return false
        return try {
            // Package visibility is granted via the manifest <queries> entry for this exact
            // package — no QUERY_ALL_PACKAGES (§17.8 App hardening).
            context.packageManager.getLaunchIntentForPackage(pkg) != null
        } catch (e: Exception) {
            false
        }
    }

    // ---------------------------------------------------------------- helpers

    fun granted(context: Context, permission: String): Boolean =
        context.checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED // API 23+; minSdk 29

    /** True when the app manifest declares [permission] (requestedPermissions list). */
    fun declared(context: Context, permission: String): Boolean = try {
        val requested = context.packageManager
            .getPackageInfo(context.packageName, PackageManager.GET_PERMISSIONS)
            .requestedPermissions
        requested != null && requested.contains(permission)
    } catch (e: Exception) {
        false
    }

    fun targetSdk(context: Context): Int = context.applicationInfo.targetSdkVersion
}
