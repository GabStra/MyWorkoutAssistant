package com.gabstra.myworkoutassistant.shared.typeconverters

import androidx.room.TypeConverter
import com.gabstra.myworkoutassistant.shared.ExerciseSessionSnapshot
import com.gabstra.myworkoutassistant.shared.adapters.ExerciseSessionSnapshotAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import java.time.LocalDateTime

class ExerciseSessionSnapshotTypeConverter {
    private val gson: Gson = GsonBuilder()
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(RestSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .registerTypeAdapter(ExerciseSessionSnapshot::class.java, ExerciseSessionSnapshotAdapter())
        .create()

    @TypeConverter
    fun fromSnapshot(snapshot: ExerciseSessionSnapshot?): String =
        gson.toJson(snapshot ?: ExerciseSessionSnapshot(), ExerciseSessionSnapshot::class.java)

    @TypeConverter
    fun toSnapshot(json: String?): ExerciseSessionSnapshot =
        if (json.isNullOrBlank()) {
            ExerciseSessionSnapshot()
        } else {
            gson.fromJson(json, ExerciseSessionSnapshot::class.java) ?: ExerciseSessionSnapshot()
        }
}
