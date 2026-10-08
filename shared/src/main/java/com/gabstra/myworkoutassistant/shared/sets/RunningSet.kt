package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

/**
 * A running effort on a RUNNING exercise carrying a [com.gabstra.myworkoutassistant.shared.running.RunningPrescription].
 * The set itself carries no duration: the runtime counts up until the prescription's
 * distance/time goal is reached, tracked by the running service (GPS).
 */
data class RunningSet(
    override val id: UUID,
    override val shouldReapplyHistoryToSet: Boolean = false
) : Set(id, shouldReapplyHistoryToSet)
