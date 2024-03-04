package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter

class ListIntConverter {
    @TypeConverter
    fun fromIntList(list: List<Int>): String {
        return list.joinToString(separator = ",", prefix = "", postfix = "")
    }

    @TypeConverter
    fun toIntList(data: String): List<Int> {
        if (data.isEmpty()) return emptyList()
        return data.split(",").map { it.toInt() }
    }
}