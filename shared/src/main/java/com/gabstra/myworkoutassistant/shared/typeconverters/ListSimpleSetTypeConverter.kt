package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.reflect.TypeToken

class ListSimpleSetTypeConverter {
    private val gson: Gson = GsonBuilder().create()

    private val listType = object : TypeToken<List<SimpleSet>>() {}.type

    @TypeConverter
    fun fromList(list: List<SimpleSet>?): String =
        if (list.isNullOrEmpty()) "[]" else gson.toJson(list, listType)

    @TypeConverter
    fun toList(json: String?): List<SimpleSet> =
        if (json.isNullOrBlank() || json == "[]") emptyList() else gson.fromJson(json, listType)
}

