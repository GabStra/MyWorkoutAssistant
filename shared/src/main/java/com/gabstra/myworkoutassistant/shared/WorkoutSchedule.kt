package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import androidx.room.TypeConverters
import com.gabstra.myworkoutassistant.shared.typeconverters.DateTypeConverter
import java.time.LocalDate
import java.util.UUID

@Entity(tableName = "workout_schedule")
data class WorkoutSchedule(
    @PrimaryKey
    val id: UUID = UUID.randomUUID(),
    val workoutId: UUID,
    val label: String = "",
    val hour: Int,
    val minute: Int,
    val isEnabled: Boolean = true,
    // Store days as a bit field: bit 0 = Sunday, bit 1 = Monday, etc.
    val daysOfWeek: Int = 0,
    // For one-time schedules
    @TypeConverters(DateTypeConverter::class)
    val specificDate: LocalDate? = null,
    // Track if this is a one-time schedule that has been executed
    val hasExecuted: Boolean = false
)
