package com.gabstra.myworkoutassistant.shared

import androidx.room.Entity
import androidx.room.PrimaryKey
import java.time.LocalDateTime

@Entity(tableName = "error_log")
data class ErrorLog(
    @PrimaryKey
    val id: String = java.util.UUID.randomUUID().toString(),
    val timestamp: LocalDateTime,
    val threadName: String,
    val exceptionType: String,
    val message: String,
    val stackTrace: String
)

