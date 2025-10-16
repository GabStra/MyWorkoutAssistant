package com.gabstra.myworkoutassistant.shared.utils

import com.gabstra.myworkoutassistant.shared.round

data class SimpleSet(val weight: Double, val reps: Int) {
    override fun equals(other: Any?): Boolean =
        this === other ||
                (other is SimpleSet &&
                        weight.round(2) == other.weight.round(2) &&
                        reps == other.reps)

    override fun hashCode(): Int = 31 * weight.round(2).hashCode() + reps
}
