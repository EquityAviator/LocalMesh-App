package ai.localmesh.meshcore

import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyInfo
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import java.security.KeyFactory
import javax.crypto.KeyGenerator
import java.security.KeyStore
import java.security.ProviderException
import java.security.Signature
import java.security.spec.ECGenParameterSpec

// §11.2 keys — createDeviceKey / signWithDeviceKey / deleteDeviceKey.
//
// §17.3 (binding): Device key = ECDSA P-256, SHA-256, DER signature, generated in Android Keystore
// (StrongBox/TEE when available), non-exportable.
//
// §17.6 (binding): the Device private key NEVER leaves the Android Keystore — never exported,
// never logged, never sent to JS. There is deliberately NO export API in this file; the only
// operations are create (idempotent), sign, and delete. The public key (SPKI) is the one value
// that crosses the bridge, which §17.6 explicitly allows.
//
// §17.10: nothing here logs key material; error messages carry only exception class names.
object DeviceKeys {

    private const val ANDROID_KEYSTORE = "AndroidKeyStore"

    data class DeviceKeyInfo(
        val publicKeySpkiB64Url: String,
        val hardwareBacked: Boolean,
    )

    /**
     * Idempotent: if a key already exists for [alias] the SAME key is returned (the pairing flow
     * treats the device public key as stable identity — §17.4 "the stored key is the one that was
     * approved"). Fresh generation only happens when the alias is absent.
     */
    fun createDeviceKey(alias: String): DeviceKeyInfo {
        require(alias.isNotBlank()) { "alias must not be blank" }
        val keyStore = keyStore()
        existingEntry(keyStore, alias)?.let { existing ->
            return DeviceKeyInfo(spkiB64UrlOf(existing), hardwareBackedOf(existing))
        }

        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, ANDROID_KEYSTORE)
        var generated = false
        // §17.3: StrongBox when available. setIsStrongBoxBacked exists since API 28; minSdk is 29,
        // so no API-level guard is needed. Unavailability is signalled either as
        // StrongBoxUnavailableException or (on some OEM keystores) as a generic ProviderException —
        // both fall back to the TEE spec below.
        try {
            generator.init(strongBoxSpec(alias))
            generator.generateKey()
            generated = true
        } catch (e: StrongBoxUnavailableException) {
            generated = false
        } catch (e: ProviderException) {
            generated = false
        }
        if (!generated) {
            generator.init(teeSpec(alias))
            generator.generateKey()
        }

        val entry = existingEntry(keyStore, alias)
            ?: throw MeshCoreException("KEYSTORE_ERROR", "key generation reported success but the entry is unreadable")
        return DeviceKeyInfo(spkiB64UrlOf(entry), hardwareBackedOf(entry))
    }

    /**
     * Signs [dataB64Url] with the alias key. §17.3: SHA256withECDSA → DER-encoded signature,
     * returned base64url no-padding. The private key participates in the signature operation
     * inside the keystore and is never extracted.
     */
    fun signWithDeviceKey(alias: String, dataB64Url: String): String {
        require(alias.isNotBlank()) { "alias must not be blank" }
        val data = try {
            B64Url.decode(dataB64Url)
        } catch (e: IllegalArgumentException) {
            throw MeshCoreException("INVALID_REQUEST", "dataB64Url is not valid base64url")
        }
        val keyStore = keyStore()
        val entry = existingEntry(keyStore, alias)
            ?: throw MeshCoreException("KEY_NOT_FOUND", "no device key for this alias")
        val signature = Signature.getInstance("SHA256withECDSA")
        signature.initSign(entry.privateKey)
        signature.update(data)
        return B64Url.encode(signature.sign())
    }

    /** Deletes the alias key. Idempotent; the auth token of a removed device should be revoked Agent-side too (§14.1). */
    fun deleteDeviceKey(alias: String) {
        require(alias.isNotBlank()) { "alias must not be blank" }
        val keyStore = keyStore()
        if (keyStore.containsAlias(alias)) {
            keyStore.deleteEntry(alias)
        }
    }

    // ---------------------------------------------------------------- internals

    private fun teeSpec(alias: String): KeyGenParameterSpec =
        KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1")) // §17.3: P-256 == secp256r1
            .setDigests(KeyProperties.DIGEST_SHA256)
            // [DESIGN] No setUserAuthenticationRequired gate in v1: agent re-auth must work without
            // per-use user presence (background reconnects). Revisit behind an ADR if the threat
            // model changes.
            .build()

    private fun strongBoxSpec(alias: String): KeyGenParameterSpec =
        KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN or KeyProperties.PURPOSE_VERIFY)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setIsStrongBoxBacked(true) // §17.3 StrongBox when available
            .build()

    private fun keyStore(): KeyStore =
        KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private fun existingEntry(keyStore: KeyStore, alias: String): KeyStore.PrivateKeyEntry? =
        try {
            if (keyStore.containsAlias(alias)) {
                keyStore.getEntry(alias, null) as? KeyStore.PrivateKeyEntry
            } else {
                null
            }
        } catch (e: Exception) {
            throw MeshCoreException("KEYSTORE_ERROR", "cannot read keystore entry: ${e.javaClass.simpleName}", e)
        }

    /** Public key export is allowed (§17.6 bans only the PRIVATE key). `publicKey.encoded` IS the DER SubjectPublicKeyInfo — the exact bytes the Agent-side pin is computed over (§17.3). */
    private fun spkiB64UrlOf(entry: KeyStore.PrivateKeyEntry): String {
        val certificate = entry.certificate
            ?: throw MeshCoreException("KEYSTORE_ERROR", "keystore entry has no certificate")
        return B64Url.encode(certificate.publicKey.encoded)
    }

    /**
     * True when the key lives in TEE/StrongBox. Unknown → false (honesty over optimism: the JS
     * layer surfaces this flag in the device list, and must not claim hardware backing it does
     * not have).
     */
    private fun hardwareBackedOf(entry: KeyStore.PrivateKeyEntry): Boolean {
        return try {
            val publicKey = entry.certificate?.publicKey ?: return false
            val factory = KeyFactory.getInstance(publicKey.algorithm, ANDROID_KEYSTORE)
            val keyInfo = factory.getKeySpec(publicKey, KeyInfo::class.java)
            if (Build.VERSION.SDK_INT >= 31) {
                // getSecurityLevel() (API 31+) supersedes the deprecated isInsideSecureHardware.
                val level = keyInfo.securityLevel
                level == KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT ||
                    level == KeyProperties.SECURITY_LEVEL_STRONGBOX
            } else {
                @Suppress("DEPRECATION")
                keyInfo.isInsideSecureHardware
            }
        } catch (e: Exception) {
            false
        }
    }
}
