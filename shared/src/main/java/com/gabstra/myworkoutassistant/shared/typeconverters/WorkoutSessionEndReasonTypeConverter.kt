package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason

class WorkoutSessionEndReasonTypeConverter {
    @TypeConverter
    fun fromWorkoutSessionEndReason(value: WorkoutSessionEndReason?): String? = value?.name

    @TypeConverter
    fun toWorkoutSessionEndReason(value: String?): WorkoutSessionEndReason =
        value
            ?.let { runCatching { WorkoutSessionEndReason.valueOf(it) }.getOrNull() }
            ?: WorkoutSessionEndReason.COMPLETED
}
