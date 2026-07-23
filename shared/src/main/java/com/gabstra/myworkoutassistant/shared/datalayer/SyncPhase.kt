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
