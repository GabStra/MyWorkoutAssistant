package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.util.UUID

@Entity(tableName = "app_info")
data class AppInfo(
    @PrimaryKey(autoGenerate = false)
    val id: Int = 1,
    val entitiesToSync: List<UUID>
)