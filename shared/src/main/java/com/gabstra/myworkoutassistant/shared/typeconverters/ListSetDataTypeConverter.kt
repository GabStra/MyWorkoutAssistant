package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import com.google.gson.reflect.TypeToken

class ListSetDataTypeConverter {
    private val gson: Gson = GsonBuilder()
        // register your polymorphic adapter for each subtype + base
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(RestSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .create()

    private val listType = object : TypeToken<List<SetData>>() {}.type

    @TypeConverter
    fun fromList(list: List<SetData>?): String =
        if (list.isNullOrEmpty()) "[]" else gson.toJson(list, listType)

    @TypeConverter
    fun toList(json: String?): List<SetData> =
        if (json.isNullOrBlank() || json == "[]") emptyList() else gson.fromJson(json, listType)
}