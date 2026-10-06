package com.gabstra.myworkoutassistant.shared.datalayer

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
