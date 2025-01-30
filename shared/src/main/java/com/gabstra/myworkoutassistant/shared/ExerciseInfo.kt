package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.util.UUID

@Entity(tableName = "exercise_info")
data class ExerciseInfo(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val bestVolume: Double,
    val bestAverageLoad: Double,
    val bestOneRepMax : Double,

    val lastSessionVolume: Double,
    val lastSessionAverageLoad: Double,
    val lastSessionOneRepMax: Double,

    val successfulSessionCounter: UInt,
    val sessionFailedCounter: UInt,

    val lastSessionWasDeload: Boolean,

    val version: UInt = 0u
)
