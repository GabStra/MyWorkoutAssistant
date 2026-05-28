package com.gabstra.myworkoutassistant.sync

internal class AutomaticSyncFingerprintState(
    var lastRequestedFingerprint: String? = null,
    var lastCompletedFingerprint: String? = null
) {
    fun shouldSkipNewAutomaticRequest(fingerprint: String): Boolean {
        return fingerprint == lastRequestedFingerprint || fingerprint == lastCompletedFingerprint
    }

    fun recordAutomaticRequest(fingerprint: String) {
        lastRequestedFingerprint = fingerprint
    }

    fun recordSuccessfulSync(fingerprint: String) {
        lastCompletedFingerprint = fingerprint
    }

    fun hasUnsentAutomaticState(): Boolean {
        return lastRequestedFingerprint != null && lastRequestedFingerprint != lastCompletedFingerprint
    }
}
