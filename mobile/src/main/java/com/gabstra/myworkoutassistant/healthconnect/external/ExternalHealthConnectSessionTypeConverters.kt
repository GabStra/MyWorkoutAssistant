package com.gabstra.myworkoutassistant.healthconnect.external

import androidx.room.TypeConverter
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

class ExternalHeartRateSampleListTypeConverter {
    private val gson = Gson()
    private val listType = object : TypeToken<List<ExternalHeartRateSample>>() {}.type

    @TypeConverter
    fun fromList(list: List<ExternalHeartRateSample>?): String =
        if (list.isNullOrEmpty()) "[]" else gson.toJson(list, listType)

    @TypeConverter
    fun toList(json: String?): List<ExternalHeartRateSample> =
        if (json.isNullOrBlank() || json == "[]") emptyList() else gson.fromJson(json, listType)
}
