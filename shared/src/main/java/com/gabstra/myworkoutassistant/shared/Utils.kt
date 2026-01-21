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
import kotlin.math.exp
import kotlin.math.ln
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt
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
    Color(0x80F0F0F0), // Not used
    Color(0xFF84B8E6), // Zone 2 (blue)    L≈0.449
    Color(0xFF92BD9A), // Zone 3 (green)   L≈0.448
    Color(0xFFE2AA2C), // Zone 1 (yellow)  L≈0.451
    Color(0xFFF2A14A), // Zone 4 (orange)  L≈0.449
    Color(0xFFF39B9B)  // Zone 5 (red)     L≈0.449
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

/**
 * Reduces the luminance (lightness) of a color while preserving its hue and saturation.
 * Uses HSL color space conversion to maintain color identity while reducing brightness.
 * 
 * @param color The original color to reduce luminance for
 * @param factor The factor by which to reduce luminance (0.0 to 1.0). 
 *               Default 0.4 means the color will be 30% of original luminance (60% reduction).
 *               Lower values result in darker colors.
 * @return A new Color with reduced luminance
 */
fun reduceColorLuminance(color: Color, factor: Float = 0.3f): Color {
    val clampedFactor = factor.coerceIn(0f, 1f)
    
    // Extract RGB components (0.0 to 1.0)
    val r = color.red
    val g = color.green
    val b = color.blue
    
    // Convert RGB to HSL
    val max = maxOf(r, g, b)
    val min = minOf(r, g, b)
    val delta = max - min
    
    // Calculate lightness (L)
    val l = (max + min) / 2f
    
    // Handle edge cases (grayscale colors)
    if (delta == 0f) {
        // Grayscale - just reduce the lightness
        val newL = (l * clampedFactor).coerceIn(0f, 1f)
        return Color(newL, newL, newL, color.alpha)
    }
    
    // Calculate saturation (S)
    val s = if (l > 0.5f) {
        delta / (2f - max - min)
    } else {
        delta / (max + min)
    }
    
    // Calculate hue (H)
    val h = when {
        max == r -> {
            val hValue = ((g - b) / delta) % 6f
            if (hValue < 0) hValue + 6f else hValue
        }
        max == g -> (b - r) / delta + 2f
        else -> (r - g) / delta + 4f
    } / 6f
    
    // Reduce lightness
    val newL = l * clampedFactor
    
    // Convert HSL back to RGB
    val c = (1f - abs(2f * newL - 1f)) * s
    val x = c * (1f - abs((h * 6f) % 2f - 1f))
    val m = newL - c / 2f
    
    val (newR, newG, newB) = when {
        h < 1f / 6f -> Triple(c, x, 0f)
        h < 2f / 6f -> Triple(x, c, 0f)
        h < 3f / 6f -> Triple(0f, c, x)
        h < 4f / 6f -> Triple(0f, x, c)
        h < 5f / 6f -> Triple(x, 0f, c)
        else -> Triple(c, 0f, x)
    }
    
    return Color(
        red = (newR + m).coerceIn(0f, 1f),
        green = (newG + m).coerceIn(0f, 1f),
        blue = (newB + m).coerceIn(0f, 1f),
        alpha = color.alpha
    )
}


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
