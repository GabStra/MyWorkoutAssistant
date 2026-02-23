package com.gabstra.myworkoutassistant.shared

/**
 * How progression is applied for an exercise.
 * OFF: no automatic progression.
 * DOUBLE_PROGRESSION: classic double progression (rep/load progression from last session).
 * AUTO_REGULATION: double progression + per-set RIR (or auto RIR) for every work set except the last.
 */
enum class ProgressionMode {
    OFF,
    DOUBLE_PROGRESSION,
    AUTO_REGULATION
}
