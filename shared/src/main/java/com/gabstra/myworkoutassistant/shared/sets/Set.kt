package com.gabstra.myworkoutassistant.shared.sets

import java.util.UUID

sealed class Set(
    open val id: UUID,
    open val shouldReapplyHistoryToSet: Boolean
) {
    // Free-text cue shown on the set screen (e.g. target rep range, load reminder).
    open val note: String? get() = null
}
