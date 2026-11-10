package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

/** Per-source sample timestamps (ms offsets), stored as a JSON object of long arrays. */
class HeartRateStreamTimesTypeConverter {
    private val gson = Gson()
    private val mapType = object : TypeToken<Map<String, List<Long>>>() {}.type

    @TypeConverter
    fun fromTimes(times: Map<String, List<Long>>): String = gson.toJson(times)

    @TypeConverter
    fun toTimes(raw: String?): Map<String, List<Long>> {
        if (raw.isNullOrBlank()) return emptyMap()
        return runCatching {
            gson.fromJson<Map<String, List<Long>>>(raw, mapType).orEmpty()
        }.getOrDefault(emptyMap())
    }
}
