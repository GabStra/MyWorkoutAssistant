package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.sync.AutomaticSyncFingerprintState
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AutomaticSyncFingerprintStateTest {

    @Test
    fun skipsRequestWhenFingerprintAlreadyRequested() {
        val state = AutomaticSyncFingerprintState(lastRequestedFingerprint = "fingerprint-a")

        assertTrue(state.shouldSkipNewAutomaticRequest("fingerprint-a"))
    }

    @Test
    fun skipsRequestWhenFingerprintAlreadyCompleted() {
        val state = AutomaticSyncFingerprintState(lastCompletedFingerprint = "fingerprint-a")

        assertTrue(state.shouldSkipNewAutomaticRequest("fingerprint-a"))
    }

    @Test
    fun reportsUnsentStateOnlyWhenRequestedDiffersFromCompleted() {
        val state = AutomaticSyncFingerprintState()

        assertFalse(state.hasUnsentAutomaticState())

        state.recordAutomaticRequest("fingerprint-a")
        assertTrue(state.hasUnsentAutomaticState())

        state.recordSuccessfulSync("fingerprint-a")
        assertFalse(state.hasUnsentAutomaticState())
    }
}
