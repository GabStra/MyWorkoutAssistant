package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

/** Per-source heart-rate streams, stored as a JSON object of int arrays. */
class HeartRateStreamsTypeConverter {
    private val gson = Gson()
    private val mapType = object : TypeToken<Map<String, List<Int>>>() {}.type

    @TypeConverter
    fun fromStreams(streams: Map<String, List<Int>>): String = gson.toJson(streams)

    @TypeConverter
    fun toStreams(raw: String?): Map<String, List<Int>> {
        if (raw.isNullOrBlank()) return emptyMap()
        return runCatching {
            gson.fromJson<Map<String, List<Int>>>(raw, mapType).orEmpty()
        }.getOrDefault(emptyMap())
    }
}
