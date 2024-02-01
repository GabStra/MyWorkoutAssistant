package com.gabstra.myworkoutassistant.shared

import android.util.Log
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.adapters.WorkoutComponentAdapter
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.GsonBuilder
import java.time.LocalDate

fun fromWorkoutStoreToJSON(workoutStore: WorkoutStore): String {
    val gson = GsonBuilder()
        .registerTypeAdapter(Exercise::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(ExerciseGroup::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(WeightSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSet::class.java, SetAdapter())
        .registerTypeAdapter(TimedDurationSet::class.java, SetAdapter())
        .registerTypeAdapter(EnduranceSet::class.java, SetAdapter())
        .create()
    return gson.toJson(workoutStore)
}


fun fromJSONToWorkoutStore(json: String): WorkoutStore {
    val gson = GsonBuilder()
        .registerTypeAdapter(WorkoutComponent::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .create()
    return gson.fromJson(json, WorkoutStore::class.java)
}

fun logLargeString(tag: String, content: String, chunkSize: Int  = 200) {
    var i = 0
    while (i < content.length) {
        Log.d(tag, content.substring(i, Math.min(content.length, i + chunkSize)))
        i += chunkSize
    }
}

fun fromAppBackupToJSON(appBackup: AppBackup) : String {
    val gson = GsonBuilder()
        .registerTypeAdapter(Exercise::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(ExerciseGroup::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(WeightSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSet::class.java, SetAdapter())
        .registerTypeAdapter(TimedDurationSet::class.java, SetAdapter())
        .registerTypeAdapter(EnduranceSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .create()

    return gson.toJson(appBackup)
}

fun fromAppBackupToJSONPrettyPrint(appBackup: AppBackup) : String {
    val gson = GsonBuilder()
        .registerTypeAdapter(Exercise::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(ExerciseGroup::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(WeightSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSet::class.java, SetAdapter())
        .registerTypeAdapter(TimedDurationSet::class.java, SetAdapter())
        .registerTypeAdapter(EnduranceSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .setPrettyPrinting()
        .create()

    return gson.toJson(appBackup)
}

fun fromJSONtoAppBackup(json: String) : AppBackup {
    val gson = GsonBuilder()
        .registerTypeAdapter(WorkoutComponent::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .create()
    return gson.fromJson(json, AppBackup::class.java)
}