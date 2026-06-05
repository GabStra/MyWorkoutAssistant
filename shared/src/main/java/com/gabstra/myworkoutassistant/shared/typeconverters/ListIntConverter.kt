package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter

class ListIntConverter {
    @TypeConverter
    fun fromIntList(list: List<Int>): String {
        return (list as List<*>)
            .mapNotNull { item ->
                when (item) {
                    is Int -> item
                    is Number -> item.toInt()
                    is String -> item.toDoubleOrNull()?.toInt()
                    else -> null
                }
            }
            .joinToString(separator = ",", prefix = "", postfix = "")
    }

    @TypeConverter
    fun toIntList(data: String): List<Int> {
        if (data.isEmpty()) return emptyList()
        return data.split(",").mapNotNull { item ->
            item.trim().takeIf { it.isNotEmpty() }?.toDoubleOrNull()?.toInt()
        }
    }
}
