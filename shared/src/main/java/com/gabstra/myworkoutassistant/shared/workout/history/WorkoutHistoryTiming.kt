package com.gabstra.myworkoutassistant.shared.workout.history

import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import java.time.LocalDateTime

/** Session start only when it was explicitly observed or supplied by the source. */
fun WorkoutHistory.knownStartTimeOrNull(): LocalDateTime? = startTime.takeIf { startTimeKnown }

/** Session duration in seconds only when it was explicitly measured or reported. */
fun WorkoutHistory.knownDurationSecondsOrNull(): Int? = duration.takeIf { durationKnown }
