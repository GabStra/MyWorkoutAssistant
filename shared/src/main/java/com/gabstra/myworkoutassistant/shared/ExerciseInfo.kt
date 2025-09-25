package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.time.LocalDate
import java.util.UUID

@Entity(tableName = "exercise_info")
data class ExerciseInfo(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val bestSession: List<SetHistory>,
    val lastSuccessfulSession: List<SetHistory>,
    val successfulSessionCounter: UInt,
    val sessionFailedCounter: UInt,
    val lastSessionWasDeload: Boolean,
    val timesCompletedInAWeek: Int = 0,
    val weeklyCompletionUpdateDate: LocalDate? = null,
    val version: UInt = 0u
)
