package com.gabstra.myworkoutassistant.shared

enum class HeartRateSource {
    WATCH_SENSOR,
    POLAR_BLE,
    WHOOP_BLE;

    val isExternal: Boolean
        get() = this != WATCH_SENSOR

    fun displayName(): String = when (this) {
        WATCH_SENSOR -> "Watch sensor"
        POLAR_BLE -> "Polar"
        WHOOP_BLE -> "WHOOP"
    }
}

sealed class ExternalHeartRateConfig {
    abstract val source: HeartRateSource
    abstract val displayName: String?
}

data class PolarHeartRateConfig(
    val deviceId: String,
    override val displayName: String? = null,
) : ExternalHeartRateConfig() {
    override val source: HeartRateSource = HeartRateSource.POLAR_BLE
}

enum class WhoopConnectionMode {
    BLE_BROADCAST
}

data class WhoopHeartRateConfig(
    val deviceId: String? = null,
    override val displayName: String? = null,
    val connectionMode: WhoopConnectionMode = WhoopConnectionMode.BLE_BROADCAST,
) : ExternalHeartRateConfig() {
    override val source: HeartRateSource = HeartRateSource.WHOOP_BLE
}

fun WorkoutStore.findExternalHeartRateConfig(source: HeartRateSource): ExternalHeartRateConfig? =
    externalHeartRateConfigs.firstOrNull { it.source == source }

fun WorkoutStore.findPolarHeartRateConfig(): PolarHeartRateConfig? =
    findExternalHeartRateConfig(HeartRateSource.POLAR_BLE) as? PolarHeartRateConfig

fun WorkoutStore.findWhoopHeartRateConfig(): WhoopHeartRateConfig? =
    findExternalHeartRateConfig(HeartRateSource.WHOOP_BLE) as? WhoopHeartRateConfig
