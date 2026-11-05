package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

class IbiRecordsTypeConverter {
    private val gson = Gson()
    private val listType = object : TypeToken<List<List<Int>>>() {}.type

    @TypeConverter
    fun fromIbiRecords(value: List<List<Int>>?): String = gson.toJson(value ?: emptyList<List<Int>>(), listType)

    @TypeConverter
    fun toIbiRecords(value: String?): List<List<Int>> =
        value?.let { runCatching { gson.fromJson<List<List<Int>>>(it, listType) }.getOrNull() }
            ?: emptyList()
}
