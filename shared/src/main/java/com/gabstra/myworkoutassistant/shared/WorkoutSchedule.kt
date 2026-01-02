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
    val specificDate: LocalDate? = null,
    val hasExecuted: Boolean = false,
    val lastNotificationSentAt : LocalDate? = null,
    val previousEnabledState: Boolean? = null
)
