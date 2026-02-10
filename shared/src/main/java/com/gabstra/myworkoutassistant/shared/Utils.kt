package com.gabstra.myworkoutassistant.shared

import android.content.Context
import android.content.pm.PackageManager
import android.util.Log
import androidx.compose.ui.graphics.Color
import com.gabstra.myworkoutassistant.shared.adapters.AccessoryEquipmentAdapter
import com.gabstra.myworkoutassistant.shared.adapters.EquipmentAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.adapters.SetDataAdapter
import com.gabstra.myworkoutassistant.shared.adapters.WorkoutComponentAdapter
import com.gabstra.myworkoutassistant.shared.adapters.WorkoutStoreAdapter
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
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
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.GsonBuilder
import com.google.gson.JsonParser
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.hypot
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.math.sqrt

fun fromWorkoutStoreToJSON(workoutStore: WorkoutStore): String {
    val gson = GsonBuilder()
        .registerTypeAdapter(Exercise::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Rest::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Superset::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Dumbbells::class.java, EquipmentAdapter())
        .registerTypeAdapter(Dumbbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(Machine::class.java, EquipmentAdapter())
        .registerTypeAdapter(PlateLoadedCable::class.java, EquipmentAdapter())
        .registerTypeAdapter(Barbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(AccessoryEquipment::class.java, AccessoryEquipmentAdapter())
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
        .registerTypeAdapter(WorkoutStore::class.java, WorkoutStoreAdapter())
        .registerTypeAdapter(WorkoutComponent::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(WeightLoadedEquipment::class.java,EquipmentAdapter())
        .registerTypeAdapter(AccessoryEquipment::class.java, AccessoryEquipmentAdapter())
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
        .registerTypeAdapter(Superset::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Dumbbells::class.java, EquipmentAdapter())
        .registerTypeAdapter(Dumbbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(Machine::class.java, EquipmentAdapter())
        .registerTypeAdapter(PlateLoadedCable::class.java, EquipmentAdapter())
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
        .registerTypeAdapter(Superset::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(Dumbbells::class.java, EquipmentAdapter())
        .registerTypeAdapter(Dumbbell::class.java, EquipmentAdapter())
        .registerTypeAdapter(Machine::class.java, EquipmentAdapter())
        .registerTypeAdapter(PlateLoadedCable::class.java, EquipmentAdapter())
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

enum class BackupFileType {
    APP_BACKUP,
    WORKOUT_STORE,
    UNKNOWN
}

/**
 * Detects the type of backup file by examining its JSON structure.
 * - AppBackup has a "WorkoutStore" field (capital W)
 * - WorkoutStore has "workouts" field at root level (lowercase)
 * 
 * @param json The JSON string to analyze
 * @return The detected file type, or UNKNOWN if detection fails
 */
fun detectBackupFileType(json: String): BackupFileType {
    return try {
        val jsonElement = JsonParser.parseString(json)
        if (!jsonElement.isJsonObject) {
            return BackupFileType.UNKNOWN
        }
        
        val jsonObject = jsonElement.asJsonObject
        
        // Check for AppBackup structure (has "WorkoutStore" field)
        if (jsonObject.has("WorkoutStore")) {
            return BackupFileType.APP_BACKUP
        }
        
        // Check for WorkoutStore structure (has "workouts" field at root)
        if (jsonObject.has("workouts")) {
            return BackupFileType.WORKOUT_STORE
        }
        
        BackupFileType.UNKNOWN
    } catch (e: Exception) {
        BackupFileType.UNKNOWN
    }
}

fun fromJSONtoAppBackup(json: String) : AppBackup {
    val gson = GsonBuilder()
        .registerTypeAdapter(WorkoutStore::class.java, WorkoutStoreAdapter())
        .registerTypeAdapter(WorkoutComponent::class.java, WorkoutComponentAdapter())
        .registerTypeAdapter(WeightLoadedEquipment::class.java,EquipmentAdapter())
        .registerTypeAdapter(AccessoryEquipment::class.java, AccessoryEquipmentAdapter())
        .registerTypeAdapter(Set::class.java, SetAdapter())
        .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
        .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
        .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
        .registerTypeAdapter(SetData::class.java, SetDataAdapter())
        .create()
    return gson.fromJson(json, AppBackup::class.java)
}

fun initializeSetData(set: Set): SetData = when (set) {
    is WeightSet -> WeightSetData(set.reps, set.weight,0.0,set.subCategory)
    is BodyWeightSet -> BodyWeightSetData(set.reps,set.additionalWeight,0.0,0.0,set.subCategory)
    is TimedDurationSet -> TimedDurationSetData(set.timeInMillis,set.timeInMillis,set.autoStart,set.autoStop)
    is EnduranceSet -> EnduranceSetData(set.timeInMillis,0,set.autoStart,set.autoStop)
    is RestSet -> RestSetData(set.timeInSeconds,set.timeInSeconds,set.subCategory)
}

fun getNewSet(set: Set): Set = when (set) {
    is WeightSet -> WeightSet(UUID.randomUUID(),set.reps, set.weight,set.subCategory)
    is BodyWeightSet -> BodyWeightSet(UUID.randomUUID(),set.reps,set.additionalWeight,set.subCategory)
    is TimedDurationSet -> TimedDurationSet(UUID.randomUUID(),set.timeInMillis,set.autoStart,set.autoStop)
    is EnduranceSet -> EnduranceSet(UUID.randomUUID(),set.timeInMillis,set.autoStart,set.autoStop)
    is RestSet -> RestSet(UUID.randomUUID(),set.timeInSeconds,set.subCategory)
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
                weight = setData.actualWeight,
                subCategory = setData.subCategory
            )
        }

        is BodyWeightSetData -> {
            return BodyWeightSet(
                id = setHistory.setId,
                reps = setData.actualReps,
                additionalWeight = setData.additionalWeight,
                subCategory = setData.subCategory
            )
        }

        is TimedDurationSetData -> {
            return TimedDurationSet(
                id = setHistory.setId,
                timeInMillis = setData.startTimer,
                autoStart = setData.autoStart,
                autoStop = setData.autoStop
            )
        }

        is EnduranceSetData -> {
            return EnduranceSet(
                id = setHistory.setId,
                timeInMillis = setData.startTimer,
                autoStart = setData.autoStart,
                autoStop = setData.autoStop
            )
        }

        is RestSetData -> {
            return RestSet(
                id = setHistory.setId,
                timeInSeconds = setData.startTimer,
                subCategory = setData.subCategory
            )
        }
    }
}

val colorsByZone = arrayOf(
    MediumLighterGray, // Not used
    Color(0xFF5ca6dd), // Blue
    Color(0xFF2bbb66), // Green
    Color(0xFFaca228), // Yellow
    Color(0xFFdf8629), // Orange
    Color(0xFFfa695e)  // Red
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

fun reduceColorLuminance(
    color: Color,
    factor: Float = 0.3f
): Color {
    val f = factor.coerceIn(0f, 1f)

    // Original
    val r0 = color.red
    val g0 = color.green
    val b0 = color.blue
    val a0 = color.alpha

    // Convert RGB -> HSL
    val max = maxOf(r0, g0, b0)
    val min = minOf(r0, g0, b0)
    val delta = max - min

    val l0 = (max + min) / 2f

    // Grayscale edge case
    if (delta == 0f) {
        val targetL = (l0 * f).coerceIn(0f, 1f)
        return Color(targetL, targetL, targetL, a0)
    }

    // Saturation
    val s0 = if (l0 > 0.5f) delta / (2f - max - min) else delta / (max + min)

    // Hue
    val h0 = (when {
        max == r0 -> {
            val hv = ((g0 - b0) / delta) % 6f
            if (hv < 0) hv + 6f else hv
        }
        max == g0 -> (b0 - r0) / delta + 2f
        else -> (r0 - g0) / delta + 4f
    } / 6f).coerceIn(0f, 1f)

    fun hslToRgb(h: Float, s: Float, l: Float): Triple<Float, Float, Float> {
        val c = (1f - kotlin.math.abs(2f * l - 1f)) * s
        val x = c * (1f - kotlin.math.abs((h * 6f) % 2f - 1f))
        val m = l - c / 2f

        val (rr, gg, bb) = when {
            h < 1f / 6f -> Triple(c, x, 0f)
            h < 2f / 6f -> Triple(x, c, 0f)
            h < 3f / 6f -> Triple(0f, c, x)
            h < 4f / 6f -> Triple(0f, x, c)
            h < 5f / 6f -> Triple(x, 0f, c)
            else -> Triple(c, 0f, x)
        }

        return Triple(
            (rr + m).coerceIn(0f, 1f),
            (gg + m).coerceIn(0f, 1f),
            (bb + m).coerceIn(0f, 1f)
        )
    }

    val targetL = (l0 * f).coerceIn(0f, 1f)
    val (cr, cg, cb) = hslToRgb(h0, s0, targetL)
    return Color(cr, cg, cb, a0)
}

/**
 * Reduces luminance via HSL lightness scaling, but guarantees a minimum contrast vs black.
 *
 * minContrastOnBlack:
 *  - 3.0f  good for non-text UI (icons, strokes)
 *  - 4.5f  for text-level readability
 *
 * If the requested factor makes the color too dark, it will return the darkest version
 * (not darker than requested) that still meets the contrast threshold. It will NOT
 * brighten beyond the original color.
 */
fun reduceColorLuminance(
    color: Color,
    factor: Float = 0.3f,
    minContrastOnBlack: Float = 2.5f
): Color {
    val f = factor.coerceIn(0f, 1f)

    // Original
    val r0 = color.red
    val g0 = color.green
    val b0 = color.blue
    val a0 = color.alpha

    // Convert RGB -> HSL
    val max = maxOf(r0, g0, b0)
    val min = minOf(r0, g0, b0)
    val delta = max - min

    val l0 = (max + min) / 2f

    // Grayscale edge case
    if (delta == 0f) {
        val targetL = (l0 * f).coerceIn(0f, 1f)
        val candidate = Color(targetL, targetL, targetL, a0)
        if (contrastOnBlack(candidate) >= minContrastOnBlack) return candidate

        // If original already below threshold, don't brighten past it
        if (contrastOnBlack(color) < minContrastOnBlack) return color

        // Binary search L in [targetL, l0] to find darkest that passes
        var lo = targetL
        var hi = l0
        var best = l0
        repeat(24) {
            val mid = (lo + hi) * 0.5f
            val midColor = Color(mid, mid, mid, a0)
            if (contrastOnBlack(midColor) >= minContrastOnBlack) {
                best = mid
                hi = mid
            } else {
                lo = mid
            }
        }
        return Color(best, best, best, a0)
    }

    // Saturation
    val s0 = if (l0 > 0.5f) delta / (2f - max - min) else delta / (max + min)

    // Hue
    val h0 = (when {
        max == r0 -> {
            val hv = ((g0 - b0) / delta) % 6f
            if (hv < 0) hv + 6f else hv
        }
        max == g0 -> (b0 - r0) / delta + 2f
        else -> (r0 - g0) / delta + 4f
    } / 6f).coerceIn(0f, 1f)

    fun hslToRgb(h: Float, s: Float, l: Float): Triple<Float, Float, Float> {
        val c = (1f - abs(2f * l - 1f)) * s
        val x = c * (1f - abs((h * 6f) % 2f - 1f))
        val m = l - c / 2f

        val (rr, gg, bb) = when {
            h < 1f / 6f -> Triple(c, x, 0f)
            h < 2f / 6f -> Triple(x, c, 0f)
            h < 3f / 6f -> Triple(0f, c, x)
            h < 4f / 6f -> Triple(0f, x, c)
            h < 5f / 6f -> Triple(x, 0f, c)
            else -> Triple(c, 0f, x)
        }

        return Triple(
            (rr + m).coerceIn(0f, 1f),
            (gg + m).coerceIn(0f, 1f),
            (bb + m).coerceIn(0f, 1f),
        )
    }

    val targetL = (l0 * f).coerceIn(0f, 1f)
    run {
        val (cr, cg, cb) = hslToRgb(h0, s0, targetL)
        val candidate = Color(cr, cg, cb, a0)
        if (contrastOnBlack(candidate) >= minContrastOnBlack) return candidate
    }

    // If original already below threshold, don't brighten past it
    if (contrastOnBlack(color) < minContrastOnBlack) return color

    // Binary search L in [targetL, l0] to find darkest that passes
    var lo = targetL
    var hi = l0
    var best = l0
    repeat(24) {
        val mid = (lo + hi) * 0.5f
        val (cr, cg, cb) = hslToRgb(h0, s0, mid)
        val midColor = Color(cr, cg, cb, a0)

        if (contrastOnBlack(midColor) >= minContrastOnBlack) {
            best = mid
            hi = mid // try darker
        } else {
            lo = mid // need brighter
        }
    }

    val (fr, fg, fb) = hslToRgb(h0, s0, best)
    return Color(fr, fg, fb, a0)
}

/**
 * WCAG-style contrast vs black, alpha-aware (blends over black in linear space).
 */
private fun contrastOnBlack(color: Color): Float =
    contrastOnBlack(color.red, color.green, color.blue, color.alpha)

private fun contrastOnBlack(r: Float, g: Float, b: Float, a: Float): Float {
    val rl = srgbToLinear(r.coerceIn(0f, 1f)) * a
    val gl = srgbToLinear(g.coerceIn(0f, 1f)) * a
    val bl = srgbToLinear(b.coerceIn(0f, 1f)) * a
    val y = 0.2126f * rl + 0.7152f * gl + 0.0722f * bl
    return (y + 0.05f) / 0.05f
}

private fun srgbToLinear(x: Float): Float =
    if (x <= 0.04045f) x / 12.92f else ((x + 0.055f) / 1.055f).pow(2.4f)


fun getMaxHearthRatePercentage(heartRate: Int, age: Int): Float{
    val mhr = 211 - (0.64f * age)
    return (heartRate / mhr) * 100
}

fun getMaxHeartRate(age: Int): Int {
    return 211 - (0.64f * age).roundToInt()
}

fun getHeartRateFromPercentage(percentage: Float, age: Int): Int {
    val mhr = getMaxHeartRate(age)
    val heartRate = (percentage/100) * mhr
    return heartRate.roundToInt()
}

fun Double.round(decimals: Int): Double {
    var multiplier = 1.0
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
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

/**
 * Determines the heart rate zone from a percentage using the zoneRanges array directly.
 * This ensures consistency with target zone detection which uses percentage ranges.
 * 
 * Note: The display code uses zoneRanges[1-5] (skipping zoneRanges[0] for 0-50%),
 * so this function maps percentages to match that display mapping:
 * - zoneRanges[1] (50-60%) → zone index 1
 * - zoneRanges[2] (60-70%) → zone index 2
 * - zoneRanges[3] (70-80%) → zone index 3
 * - zoneRanges[4] (80-90%) → zone index 4
 * - zoneRanges[5] (90-100%) → zone index 5
 * 
 * @param percentage The heart rate percentage (0-100)
 * @return Zone index (1-5) matching the colorsByZone array and display code
 */
fun getZoneFromPercentage(percentage: Float): Int {
    // Find which zoneRanges entry the percentage falls into
    // Use the same inclusive boundary logic as target zone detection
    // Iterate backwards to handle boundary overlaps (e.g., 50% is in both [0] and [1], prefer [1])
    for (i in zoneRanges.indices.reversed()) {
        val (lower, upper) = zoneRanges[i]
        // Use inclusive bounds to match target zone check: percentage in lower..upper
        if (percentage in lower..upper) {
            return i
        }
    }
    // Fallback: clamp to valid range
    return when {
        percentage < 0f -> 0
        percentage > 100f -> zoneRanges.size - 1
        else -> 0 // Should not reach here, but handle edge cases
    }
}

fun getVersionName(context: Context): String? {
    return try {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName
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

/**
 * Exercise category for evidence-based warm-up volume (NSCA/ACSM).
 * Heavy compound: high axial load (squat, deadlift, bench, OHP, rows). Moderate: lunges, split squats, hip thrusts, machine presses, pull-ups. Isolation: curls, lateral raises, triceps, calf raises.
 */
enum class ExerciseCategory {
    HEAVY_COMPOUND,
    MODERATE_COMPOUND,
    ISOLATION
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

fun formatNumber(number: Double): String {
    val suffixes = listOf("", "K", "M", "B", "T")
    var value = number
    var suffixIndex = 0

    while (value >= 1000 && suffixIndex < suffixes.lastIndex) {
        value /= 1000
        suffixIndex++
    }

    return when {
        value == 0.0 -> "0"
        value >= 100 -> "%.0f%s".format(value, suffixes[suffixIndex])
        value >= 10 -> "%.1f%s".format(value, suffixes[suffixIndex])
        else -> "%.2f%s".format(value, suffixes[suffixIndex])
    }.replace(",",".").replace(Regex("\\.0+$"), "")
}

fun Double.isEqualTo(other: Double, epsilon: Double = 1e-2): Boolean {
    return abs(this - other) < epsilon
}

object OneRM {
    private const val REP_CAP = 80.0 // practical upper bound for reps

    // Mayhew %1RM model: %1RM = 0.522 + 0.419 * e^(−0.055 * reps)
    fun percent1RM(reps: Int): Double {
        require(reps >= 1.0) { "reps must be >= 1" }
        return 0.522 + 0.419 * exp(-0.055 * reps)
    }

    // e1RM from a submax set (weight, reps)
    fun estimate1RM(weight: Double, reps: Int): Double {
        require(weight > 0 && reps > 0)
        return weight / percent1RM(reps)
    }

    // Max reps possible at given weight for a known 1RM (invert Mayhew)
    fun maxRepsForWeight(weight: Double, oneRepMax: Double): Double {
        require(weight > 0 && oneRepMax > 0)
        val i = (weight / oneRepMax).coerceIn(1e-9, 1.0) // fraction of 1RM
        if (i >= 1.0) return 1.0
        if (i <= 0.522) return REP_CAP // ≤52.2% 1RM ⇒ very high reps; cap
        val arg = (i - 0.522) / 0.419
        // numerical safety: clamp into (0,1]
        val safe = min(1.0, max(1e-12, arg))
        val reps = -ln(safe) / 0.055
        return reps.coerceIn(1.0, REP_CAP)
    }

    fun calculateRIR(weight: Double, reps: Int, oneRepMax: Double): Double =
        maxRepsForWeight(weight, oneRepMax) - reps

    fun calculateOneRepMax(weight: Double, reps: Int): Double =
        estimate1RM(weight, reps)

    fun repsForTargetRIR(weight: Double, oneRepMax: Double, targetRIR: Double): Double {
        require(weight > 0 && oneRepMax > 0)
        val maxReps = maxRepsForWeight(weight, oneRepMax)
        return (maxReps - targetRIR).coerceAtLeast(1.0)
    }
}

fun List<Double>.median(): Double {
    require(this.isNotEmpty()) { "List is empty" }
    val sorted = this.sorted()
    val n = sorted.size
    return if (n % 2 == 1) {
        sorted[n / 2]
    } else {
        (sorted[n / 2 - 1] + sorted[n / 2]) / 2.0
    }
}

fun List<Double>.standardDeviation(): Double {
    if (this.isEmpty()) {
        throw IllegalArgumentException("Cannot calculate standard deviation of empty list")
    }

    val mean = this.average()
    val variance = this.fold(0.0) { acc, num ->
        acc + (num - mean).pow(2)
    } / this.size

    return sqrt(variance)
}

fun List<Double>.coefficientOfVariation(): Double {
    if (this.isEmpty()) {
        throw IllegalArgumentException("Cannot calculate coefficient of variation of an empty list.")
    }

    val mean = this.average()
    val stdDev = this.standardDeviation()

    // Handle the edge case where the mean is 0.
    if (mean == 0.0) {
        // If the standard deviation is also 0, there's no variation.
        // Otherwise, the relative variation is infinitely large.
        return if (stdDev == 0.0) 0.0 else Double.POSITIVE_INFINITY
    }

    return stdDev / mean
}


fun formatWeight(weight:Double): String {
    if (weight % 1.0 == 0.0) {
        return weight.toInt().toString()
    }

    return "%.2f".format(weight).replace(",", ".")
}

fun <T> removeRestAndRestPause(
    sets: List<T>,
    isRestPause: (T) -> Boolean,
    isRestSet: (T) -> Boolean
): List<T> {
    val out = ArrayList<T>(sets.size)
    for (s in sets) {
        if (isRestPause(s)) {
            while (out.isNotEmpty() && isRestSet(out.last())) {
                out.removeAt(out.lastIndex)
            }
            continue // drop the rest-pause set itself
        }
        out += s
    }
    return out
}

/**
 * Moves `from`'s OKLCH hue towards `to`'s hue by `amount` (0..1),
 * keeping `from`'s lightness (L) and chroma (C) unchanged.
 *
 * Notes:
 * - If either color is near-gray (very low chroma), hue is undefined -> returns `from`.
 * - Uses OKLab <-> OKLCH conversions (per Björn Ottosson's OKLab definition).
 */
fun tintHueTowardsOklch(
    from: Color,
    to: Color,
    amount: Float,
    neutralChroma: Float = 0.03f, // typical 0.02–0.05 for “tinted white”
): Color {
    val t = amount.coerceIn(0f, 1f)

    val (L1, C1, h1) = from.toOklch()
    val (L2, C2, h2) = to.toOklch()

    val chromaEps = 1e-4f

    val outHue: Float
    val outChroma: Float

    if (C1 < chromaEps) {
        outHue = h2
        outChroma = neutralChroma.coerceIn(0f, 0.2f)
    } else if (C2 < chromaEps) {
        // target neutral -> nothing meaningful to tint towards
        return from
    } else {
        outHue = lerpHueDegrees(h1, h2, t)
        outChroma = C1 // keep original chroma
    }

    return Color.fromOklch(L1, outChroma, outHue, from.alpha)
}

/** Convenience extension. */
fun Color.hueTowards(target: Color, amount: Float = 0.35f): Color =
    tintHueTowardsOklch(this, target, amount)

/* ----------------------------- OKLCH helpers ----------------------------- */

data class Oklch(val L: Float, val C: Float, val hDeg: Float)

private fun Color.toOklch(): Oklch {
    val (L, a, b) = toOklab()
    val C = hypot(a, b)
    val hRad = atan2(b, a) // [-pi, pi]
    val hDeg = ((hRad * 180.0 / Math.PI).toFloat() + 360f) % 360f
    return Oklch(L, C, hDeg)
}

private fun Color.Companion.fromOklch(L: Float, C: Float, hDeg: Float, alpha: Float = 1f): Color {
    val hRad = (hDeg * Math.PI / 180.0).toFloat()
    val a = C * cos(hRad)
    val b = C * sin(hRad)
    return fromOklab(L, a, b, alpha)
}

/* ----------------------------- Hue interpolation ----------------------------- */

private fun lerpHueDegrees(h1: Float, h2: Float, t: Float): Float {
    // shortest path around the circle
    var delta = (h2 - h1) % 360f
    if (delta > 180f) delta -= 360f
    if (delta < -180f) delta += 360f
    return (h1 + delta * t + 360f) % 360f
}

/* ----------------------------- OKLab conversion ----------------------------- */

private data class Oklab(val L: Float, val a: Float, val b: Float)

private fun Color.toOklab(): Oklab {
    val r = srgbToLinear(red)
    val g = srgbToLinear(green)
    val b = srgbToLinear(blue)

    // linear sRGB -> LMS
    val l = 0.4122214708f * r + 0.5363325363f * g + 0.0514459929f * b
    val m = 0.2119034982f * r + 0.6806995451f * g + 0.1073969566f * b
    val s = 0.0883024619f * r + 0.2817188376f * g + 0.6299787005f * b

    val l_ = cbrt(l)
    val m_ = cbrt(m)
    val s_ = cbrt(s)

    // LMS -> OKLab
    val L = 0.2104542553f * l_ + 0.7936177850f * m_ - 0.0040720468f * s_
    val A = 1.9779984951f * l_ - 2.4285922050f * m_ + 0.4505937099f * s_
    val B = 0.0259040371f * l_ + 0.7827717662f * m_ - 0.8086757660f * s_

    return Oklab(L, A, B)
}

private fun Color.Companion.fromOklab(L: Float, a: Float, b: Float, alpha: Float = 1f): Color {
    // OKLab -> LMS'
    val l_ = L + 0.3963377774f * a + 0.2158037573f * b
    val m_ = L - 0.1055613458f * a - 0.0638541728f * b
    val s_ = L - 0.0894841775f * a - 1.2914855480f * b

    // cube
    val l = l_ * l_ * l_
    val m = m_ * m_ * m_
    val s = s_ * s_ * s_

    // LMS -> linear sRGB
    val rLin = +4.0767416621f * l - 3.3077115913f * m + 0.2309699292f * s
    val gLin = -1.2684380046f * l + 2.6097574011f * m - 0.3413193965f * s
    val bLin = -0.0041960863f * l - 0.7034186147f * m + 1.7076147010f * s

    val r = linearToSrgb(rLin).coerceIn(0f, 1f)
    val g = linearToSrgb(gLin).coerceIn(0f, 1f)
    val bb = linearToSrgb(bLin).coerceIn(0f, 1f)

    return Color(r, g, bb, alpha)
}

/* ----------------------------- sRGB helpers ----------------------------- */

private fun linearToSrgb(c: Float): Float =
    if (c <= 0.0031308f) 12.92f * c else 1.055f * c.pow(1f / 2.4f) - 0.055f

private fun cbrt(x: Float): Float = x.pow(1f / 3f)