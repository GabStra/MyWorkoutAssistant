package com.gabstra.myworkoutassistant.shared

import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import androidx.compose.ui.graphics.Color
import com.gabstra.myworkoutassistant.shared.adapters.EquipmentAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.adapters.WorkoutComponentAdapter
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Equipment
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetData
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.GsonBuilder
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream

fun fromWorkoutStoreToJSON(workoutStore: WorkoutStore): String {
    val gson = GsonBuilder()
        .registerTypeAdapter(Exercise::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Rest::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Dumbbells::class.java, EquipmentAdapter())
        .registerTypeAdapter(Barbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(WeightSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSet::class.java, SetAdapter())
        .registerTypeAdapter(TimedDurationSet::class.java, SetAdapter())
        .registerTypeAdapter(EnduranceSet::class.java, SetAdapter())
        .registerTypeAdapter(RestSet::class.java, SetAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .create()
    return gson.toJson(workoutStore)
}


fun fromJSONToWorkoutStore(json: String): WorkoutStore {
    val gson = GsonBuilder()
        .registerTypeAdapter(WorkoutComponent::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Equipment::class.java,EquipmentAdapter())
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
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
        .registerTypeAdapter(Rest::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Dumbbells::class.java, EquipmentAdapter())
        .registerTypeAdapter(Barbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(WeightSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSet::class.java, SetAdapter())
        .registerTypeAdapter(TimedDurationSet::class.java, SetAdapter())
        .registerTypeAdapter(EnduranceSet::class.java, SetAdapter())
        .registerTypeAdapter(RestSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(RestSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .create()

    return gson.toJson(appBackup)
}

fun fromAppBackupToJSONPrettyPrint(appBackup: AppBackup) : String {
    val gson = GsonBuilder()
        .registerTypeAdapter(Exercise::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Rest::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Dumbbells::class.java, EquipmentAdapter())
        .registerTypeAdapter(Barbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(WeightSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSet::class.java, SetAdapter())
        .registerTypeAdapter(TimedDurationSet::class.java, SetAdapter())
        .registerTypeAdapter(EnduranceSet::class.java, SetAdapter())
        .registerTypeAdapter(RestSet::class.java, SetAdapter())
        .registerTypeAdapter(BodyWeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(EnduranceSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(TimedDurationSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(WeightSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(RestSetData::class.java, SetDataAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .setPrettyPrinting()
        .create()

    return gson.toJson(appBackup)
}

fun fromJSONtoAppBackup(json: String) : AppBackup {
    val gson = GsonBuilder()
        .registerTypeAdapter(WorkoutComponent::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Equipment::class.java,EquipmentAdapter())
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .create()
    return gson.fromJson(json, AppBackup::class.java)
}

fun initializeSetData(set: Set): SetData = when (set) {
    is WeightSet -> WeightSetData(set.reps, set.weight)
    is BodyWeightSet -> BodyWeightSetData(set.reps,set.additionalWeight,0.0)
    is TimedDurationSet -> TimedDurationSetData(set.timeInMillis,set.timeInMillis)
    is EnduranceSet -> EnduranceSetData(set.timeInMillis,0)
    is RestSet -> RestSetData(set.timeInSeconds,set.timeInSeconds)
}

fun getNewSet(set: Set): Set = when (set) {
    is WeightSet -> WeightSet(UUID.randomUUID(),set.reps, set.weight)
    is BodyWeightSet -> BodyWeightSet(UUID.randomUUID(),set.reps,set.additionalWeight)
    is TimedDurationSet -> TimedDurationSet(UUID.randomUUID(),set.timeInMillis,set.autoStart,set.autoStop)
    is EnduranceSet -> EnduranceSet(UUID.randomUUID(),set.timeInMillis,set.autoStart,set.autoStop)
    is RestSet -> RestSet(UUID.randomUUID(),set.timeInSeconds)
}

fun copySetData(setData: SetData): SetData = when (setData) {
    is WeightSetData -> setData.copy()
    is BodyWeightSetData -> setData.copy()
    is TimedDurationSetData -> setData.copy()
    is EnduranceSetData -> setData.copy()
    is RestSetData -> setData.copy()
}

fun isSetDataValid(set: Set, setData: SetData): Boolean {
    return when (set) {
        is WeightSet -> setData is WeightSetData
        is BodyWeightSet -> setData is BodyWeightSetData
        is TimedDurationSet -> setData is TimedDurationSetData
        is EnduranceSet -> setData is EnduranceSetData
        is RestSet -> setData is RestSetData
    }
}

fun getNewSetFromSetHistory(setHistory: SetHistory): Set {
    when (val setData = setHistory.setData) {
        is WeightSetData -> {
            return WeightSet(
                id = setHistory.setId,
                reps = setData.actualReps,
                weight = setData.actualWeight
            )
        }

        is BodyWeightSetData -> {
            return BodyWeightSet(
                id = setHistory.setId,
                reps = setData.actualReps,
                additionalWeight = setData.additionalWeight
            )
        }

        is TimedDurationSetData -> {
            return TimedDurationSet(
                id = setHistory.setId,
                timeInMillis = setData.startTimer,
                autoStart = false,
                autoStop = false
            )
        }

        is EnduranceSetData -> {
            return EnduranceSet(
                id = setHistory.setId,
                timeInMillis = setData.startTimer,
                autoStart = false,
                autoStop = false
            )
        }

        is RestSetData -> {
            return RestSet(
                id = setHistory.setId,
                timeInSeconds = setData.startTimer,
            )
        }
    }
}

fun getNewSetFromSetHistory(set: Set, setData: SetData): Set? {
    when (set) {
        is WeightSet -> {
            if (setData is WeightSetData) {
                return set.copy(
                    reps = setData.actualReps,
                    weight = setData.actualWeight
                )
            }
        }

        is BodyWeightSet -> {
            if (setData is BodyWeightSetData) {
                return set.copy(
                    reps = setData.actualReps,
                    additionalWeight = setData.additionalWeight,
                )
            }
        }

        is TimedDurationSet -> {
            if (setData is TimedDurationSetData) {
                return set.copy(
                    timeInMillis = setData.startTimer
                )
            }
        }

        is EnduranceSet -> {
            if (setData is EnduranceSetData) {
                return set.copy(
                    timeInMillis = setData.startTimer
                )
            }
        }

        is RestSet -> {
            if (setData is RestSetData) {
                return set.copy(
                    timeInSeconds = setData.startTimer
                )
            }
        }
    }

    return null
}

val colorsByZone = arrayOf(
    Color.hsl(0f, 0.02f, 0.68f),
    Color.hsl(208f, 0.61f, 0.76f),
    Color.hsl(200f, 0.66f, 0.49f),
    Color.hsl(113f, 0.79f, 0.34f),
    Color.hsl(27f, 0.97f, 0.54f),
    Color.hsl(9f, 0.88f, 0.45f)
)

//define an array that for each zone, contains the upper and lower limit in percentage
val zoneRanges = arrayOf(
    0f to 50f,
    50f to 60f,
    60f to 70f,
    70f to 80f,
    80f to 90f,
    90f to 100f
)


fun getMaxHearthRatePercentage(heartRate: Int, age: Int): Float{
    val mhr = 208 - (0.7f * age)
    return (heartRate / mhr) * 100
}

fun getMaxHeartRate(age: Int): Int {
    return 208 - (0.7f * age).toInt()
}

fun getHeartRateFromPercentage(percentage: Float, age: Int): Int {
    val mhr = getMaxHeartRate(age)
    val heartRate = (percentage/100) * mhr
    return heartRate.toInt()
}

fun mapPercentage(percentage: Float): Float {
    return if (percentage <= 50) {
        percentage * 0.00332f
    } else {
        0.166f + ((percentage - 50) / 10) * 0.166f
    }
}

fun mapPercentageToZone(percentage: Float): Int {
    val mappedValue = if (percentage <= 50) {
        percentage * 0.00332f
    } else {
        0.166f + ((percentage - 50) / 10) * 0.166f
    }

    val zone = (mappedValue / 0.166f).toInt()
    return if (zone > 5) 5 else zone
}

fun getVersionName(context: Context): String {
    return try {
        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.P) {
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        } else {
            @Suppress("DEPRECATION")
            context.packageManager.getPackageInfo(context.packageName, 0).versionName
        }
    } catch (e: PackageManager.NameNotFoundException) {
        e.printStackTrace()
        ""
    }
}

enum class SetType {
    COUNTUP_SET, BODY_WEIGHT_SET, COUNTDOWN_SET, WEIGHT_SET
}

enum class ExerciseType {
    COUNTUP, BODY_WEIGHT, COUNTDOWN, WEIGHT
}

fun getSetTypeFromSet(set: Set): SetType {
    return when (set) {
        is WeightSet -> SetType.WEIGHT_SET
        is BodyWeightSet -> SetType.BODY_WEIGHT_SET
        is EnduranceSet -> SetType.COUNTUP_SET
        is TimedDurationSet -> SetType.COUNTDOWN_SET
        is RestSet -> throw IllegalArgumentException("RestSet is not a valid set type")
    }
}

fun getExerciseTypeFromSet(set: Set): ExerciseType {
    return when (getSetTypeFromSet(set)) {
        SetType.WEIGHT_SET -> ExerciseType.WEIGHT
        SetType.BODY_WEIGHT_SET -> ExerciseType.BODY_WEIGHT
        SetType.COUNTUP_SET -> ExerciseType.COUNTUP
        SetType.COUNTDOWN_SET -> ExerciseType.COUNTDOWN
    }
}

fun getAllPreviousVersions(workouts: List<Workout>, currentWorkout: Workout): List<Workout> {
    val previousVersions = mutableListOf<Workout>()
    var workout = currentWorkout

    while (workout.previousVersionId != null) {
        val previousVersion = workouts.find { it.id == workout.previousVersionId }
        if (previousVersion != null) {
            previousVersions.add(previousVersion)
            workout = previousVersion
        } else {
            break
        }
    }

    return previousVersions
}

fun compressString(data: String): ByteArray {
    val byteArrayOutputStream = ByteArrayOutputStream()
    GZIPOutputStream(byteArrayOutputStream).use { gzipStream ->
        gzipStream.write(data.toByteArray(Charsets.UTF_8))
    }
    return byteArrayOutputStream.toByteArray()
}

fun decompressToString(data: ByteArray): String {
    return GZIPInputStream(ByteArrayInputStream(data)).bufferedReader(Charsets.UTF_8).use { it.readText() }
}
