package com.gabstra.myworkoutassistant.shared.datalayer

import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

enum class SyncPhase {
    CONNECTING,
    TRANSFERRING,
    PROCESSING,
    COMPLETED;

    companion object {
        fun fromWireValue(value: String?): SyncPhase? =
            entries.firstOrNull { phase -> phase.name == value }
    }
}

data class SyncProgressUpdate(
    val phase: SyncPhase,
    val progress: Float
) {
    fun toByteArray(): ByteArray =
        "${phase.name}|${progress.coerceIn(0f, 1f)}".toByteArray(Charsets.UTF_8)

    companion object {
        fun fromByteArray(bytes: ByteArray): SyncProgressUpdate? {
            val parts = bytes.toString(Charsets.UTF_8).split('|', limit = 2)
            if (parts.size != 2) return null
            val phase = SyncPhase.fromWireValue(parts[0]) ?: return null
            val progress = parts[1].toFloatOrNull()?.takeIf(Float::isFinite) ?: return null
            return SyncProgressUpdate(phase, progress.coerceIn(0f, 1f))
        }
    }
}

/**
 * Fast syncs blast through CONNECTING → TRANSFERRING → PROCESSING in milliseconds;
 * holding each phase on screen keeps the staged loader readable on both devices
 * and shows the same steps in the same order.
 */
class StagedPhaseDisplay(
    private val scope: kotlinx.coroutines.CoroutineScope,
    private val minimumHoldMillis: Long = 800L,
) {
    private var pending: Job? = null

    @Volatile
    private var pendingPhase: SyncPhase? = null

    @Volatile
    private var lastUiUpdateMillis = 0L

    /**
     * Call on every UI update — including same-phase progress ticks — so a pending
     * phase switch waits for the currently displayed stage's full hold.
     */
    fun onUiUpdated() {
        lastUiUpdateMillis = System.currentTimeMillis()
    }

    fun show(
        phase: SyncPhase,
        currentPhase: SyncPhase?,
        publish: (SyncPhase) -> Unit,
    ) {
        if (phase == currentPhase) {
            pending?.cancel()
            pending = null
            pendingPhase = null
            onUiUpdated()
            publish(phase)
            return
        }
        if (phase == pendingPhase) {
            // Already scheduled; the hold re-measures when the job resumes, so this
            // progress tick simply postpones the switch until the stage has been
            // fully visible (the 100% ring included) for the minimum hold.
            onUiUpdated()
            return
        }
        val previous = pending
        pendingPhase = phase
        pending = scope.launch {
            previous?.join()
            val wait = minimumHoldMillis - (System.currentTimeMillis() - lastUiUpdateMillis)
            if (wait > 0) delay(wait)
            onUiUpdated()
            pendingPhase = null
            publish(phase)
        }
    }

    fun cancel() {
        pending?.cancel()
        pending = null
        pendingPhase = null
    }
}
