package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.util.UUID

@Entity(tableName = "exercise_info")
data class ExerciseInfo(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val bestVolume: Double,
    val oneRepMax: Double,
    val version: UInt = 0u
)
