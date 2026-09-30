package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.running.RunningResult
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

class RunningResultsTypeConverter {
    private val gson = Gson()
    private val listType = object : TypeToken<List<RunningResult>>() {}.type

    @TypeConverter
    fun fromRunningResults(value: List<RunningResult>?): String = gson.toJson(value ?: emptyList<RunningResult>(), listType)

    @TypeConverter
    fun toRunningResults(value: String?): List<RunningResult> =
        value?.let { runCatching { gson.fromJson<List<RunningResult>>(it, listType) }.getOrNull() }
            ?: emptyList()
}
