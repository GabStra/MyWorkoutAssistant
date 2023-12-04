package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.SetDataAdapter

import com.google.gson.GsonBuilder

class SetDataTypeConverter {
    @TypeConverter
    fun fromSetData(set: SetData): String {
        val gson = GsonBuilder()
            .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
            .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
            .create()
        return gson.toJson(set)
    }

    @TypeConverter
    fun toSetData(setData: String): SetData {
        val gson = GsonBuilder()
            .registerTypeAdapter(SetData::class.java, SetDataAdapter())
            .create()

        // Deserialize from JSON
        // Note: You need to handle the deserialization logic based on the type of exercise
        return gson.fromJson(setData, SetData::class.java)
    }
}