package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import java.util.UUID

@Entity(tableName = "exercise_info")
data class ExerciseInfo(
    @PrimaryKey(autoGenerate = false)
    val id: UUID,
    val bestSession: List<SetData>,
    val lastSuccessfulSession: List<SetData>,
    val successfulSessionCounter: UInt,
    val sessionFailedCounter: UInt,
    val lastSessionWasDeload: Boolean,
    val version: UInt = 0u
)
