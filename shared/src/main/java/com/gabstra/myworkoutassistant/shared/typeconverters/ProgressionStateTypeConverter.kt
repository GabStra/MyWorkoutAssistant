package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState

class ProgressionStateTypeConverter {
    @TypeConverter
    fun fromProgressionState(value: ProgressionState): String {
        return value.name
    }

    @TypeConverter
    fun toProgressionState(value: String): ProgressionState {
        return ProgressionState.valueOf(value)
    }
}


