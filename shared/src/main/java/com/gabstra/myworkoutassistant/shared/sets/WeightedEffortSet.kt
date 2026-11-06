package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

/**
 * A load-carrying count-up effort (sled push, farmer carry): the athlete works
 * against an external load until the distance or time goal is reached. Unlike
 * [WeightSet] there are no reps; unlike [EnduranceSet] the load is the point,
 * not an accessory. The goal lives on the set so per-set distances can vary.
 */
data class WeightedEffortSet(
    override val id: UUID,
    val targetDistanceMeters: Double? = null,
    val timeInMillis: Int? = null,
    val targetWeight: Double? = null,
    val autoStart: Boolean = true,
    val autoStop: Boolean = false,
    override val shouldReapplyHistoryToSet: Boolean = false,
    override val note: String? = null
) : Set(id, shouldReapplyHistoryToSet)
