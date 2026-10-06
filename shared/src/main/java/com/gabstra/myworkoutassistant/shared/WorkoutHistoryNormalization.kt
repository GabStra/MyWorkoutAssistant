package com.gabstra.myworkoutassistant.shared

fun WorkoutHistory.normalizedHeartBeatRecords(): WorkoutHistory {
    val normalizedRecords = (heartBeatRecords as List<*>).mapNotNull { sample ->
        when (sample) {
            is Int -> sample
            is Number -> sample.toInt()
            is String -> sample.toDoubleOrNull()?.toInt()
            else -> null
        }
    }
    return if (normalizedRecords == heartBeatRecords) {
        this
    } else {
        copy(heartBeatRecords = normalizedRecords)
    }
}

fun AppBackup.normalizedWorkoutHistories(): AppBackup =
    copy(WorkoutHistories = WorkoutHistories.map { it.normalizedHeartBeatRecords() })
