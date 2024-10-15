package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import java.util.UUID

class UUIDListConverter {
    @TypeConverter
    fun fromUUIDList(uuids: List<UUID>): String {
        return uuids.joinToString(",") { it.toString() }
    }

    @TypeConverter
    fun toUUIDList(data: String): List<UUID> {
        return data.split(",").map { UUID.fromString(it) }
    }
}