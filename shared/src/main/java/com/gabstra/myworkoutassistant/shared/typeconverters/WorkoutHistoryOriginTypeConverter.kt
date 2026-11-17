package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin

class WorkoutHistoryOriginTypeConverter {
    @TypeConverter
    fun fromOrigin(value: WorkoutHistoryOrigin): String = value.name

    @TypeConverter
    fun toOrigin(value: String): WorkoutHistoryOrigin =
        runCatching { WorkoutHistoryOrigin.valueOf(value) }
            .getOrDefault(WorkoutHistoryOrigin.RECORDED)
}
