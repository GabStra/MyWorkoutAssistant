package com.gabstra.myworkoutassistant

import android.annotation.SuppressLint
import android.content.ContentValues
import android.content.Context
import android.os.Environment
import android.provider.MediaStore
import android.widget.Toast
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.metadata.Device
import androidx.health.connect.client.records.metadata.Metadata
import androidx.health.connect.client.units.Energy
import androidx.health.connect.client.units.Mass
import com.gabstra.myworkoutassistant.composables.FilterRange
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.MediumLightGray
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.compressString
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.temporal.TemporalAdjusters
import java.util.UUID
import java.util.concurrent.CancellationException
import kotlin.math.pow

fun sendWorkoutStore(dataClient: DataClient, workoutStore: WorkoutStore) {
    try {
        val jsonString = fromWorkoutStoreToJSON(workoutStore)
        val compressedData = compressString(jsonString)
        val request = PutDataMapRequest.create("/workoutStore").apply {
            dataMap.putByteArray("compressedJson",compressedData)
            dataMap.putString("timestamp",System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
    } catch (cancellationException: CancellationException) {
        cancellationException.printStackTrace()
    } catch (exception: Exception) {
        exception.printStackTrace()
    }
}

suspend fun sendAppBackup(dataClient: DataClient, appBackup: AppBackup) {
    try {
        val jsonString = fromAppBackupToJSON(appBackup)
        val chunkSize = 50000 // Adjust the chunk size as needed
        val compressedData = compressString(jsonString)
        val chunks = compressedData.asList().chunked(chunkSize)

        val transactionId = UUID.randomUUID().toString()

        val startRequest = PutDataMapRequest.create("/backupChunkPath").apply {
            dataMap.putBoolean("isStart", true)
            dataMap.putInt("chunksCount", chunks.size)
            dataMap.putString("timestamp", System.currentTimeMillis().toString())
            dataMap.putString("transactionId", transactionId)
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(startRequest)

        delay(500)

        chunks.forEachIndexed { index, chunk ->
            val isLastChunk = index == chunks.size - 1

            val request = PutDataMapRequest.create("/backupChunkPath").apply {
                dataMap.putByteArray("chunk", chunk.toByteArray())
                if(isLastChunk) {
                    dataMap.putBoolean("isLastChunk", true)
                }
                dataMap.putString("timestamp", System.currentTimeMillis().toString())
                dataMap.putString("transactionId", transactionId)
            }.asPutDataRequest().setUrgent()

            dataClient.putDataItem(request)

            if (!isLastChunk) {
                delay(500)
            }
        }
    } catch (cancellationException: CancellationException) {
        cancellationException.printStackTrace()
    } catch (exception: Exception) {
        exception.printStackTrace()
    }
}

fun formatSecondsToMinutesSeconds(seconds: Int): String {
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return String.format("%02d:%02d", minutes, remainingSeconds)
}

fun formatMillisecondsToMinutesSeconds(milliseconds: Int): String {
    val seconds = milliseconds / 1000

    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    val remainingMilliseconds = milliseconds % 1000
    return String.format("%02d:%02d:%03d", minutes, remainingSeconds, remainingMilliseconds)
}

fun findWorkoutComponentByIdInWorkouts(workouts: List<Workout>, id: UUID): WorkoutComponent? {
    for(workout in workouts){
        for (workoutComponent in workout.workoutComponents) {
            if (workoutComponent.id == id) {
                return workoutComponent
            }

            if(workoutComponent is Superset){
                workoutComponent.exercises.forEach { exercise ->
                    if(exercise.id == id){
                        return exercise
                    }
                }
            }
        }
    }


    return null
}

fun findWorkoutComponentByIdInWorkout(workout: Workout, id: UUID): WorkoutComponent? {
    for (workoutComponent in workout.workoutComponents) {
        if (workoutComponent.id == id) {
            return workoutComponent
        }

        if(workoutComponent is Superset){
            if (workoutComponent.id == id) {
                return workoutComponent
            }

            workoutComponent.exercises.forEach { exercise ->
                if(exercise.id == id){
                    return exercise
                }
            }
        }
    }

    return null
}

fun writeJsonToDownloadsFolder(context: Context, fileName: String, fileContent: String) {
    val contentValues = ContentValues().apply {
        put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
        put(MediaStore.MediaColumns.MIME_TYPE, "application/json")
        put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
    }

    val resolver = context.contentResolver
    val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, contentValues)

    uri?.let {
        resolver.openOutputStream(it).use { outputStream ->
            outputStream?.write(fileContent.toByteArray())
        }
    } ?: run {
        Toast.makeText(context, "Failed to write to downloads folder", Toast.LENGTH_SHORT).show()
    }
}

fun Modifier.optionalClip(shape:RoundedCornerShape?): Modifier {
    return if (shape != null) {
        clip(shape)
    } else {
        this
    }
}

fun formatTime(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60
    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}

fun formatTimeHourMinutes(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60

    return String.format("%02d:%02d", hours, minutes)
}

fun getEnabledStatusOfWorkoutComponent(workoutComponent: WorkoutComponent): Boolean {
    return when (workoutComponent) {
        is Exercise -> workoutComponent.enabled
        is Rest -> workoutComponent.enabled
        else -> false // Default case if the component type is unknown
    }
}

fun getStartOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
}

fun getEndOfWeek(date: LocalDate): LocalDate {
    return date.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY))
}

fun getOneRepMax(weight: Double, reps: Int): Double {
    return weight / (1.0278f - (0.0278f * reps))
}

fun calculateKiloCaloriesBurned(
    age: Int,
    weightKg: Double,
    averageHeartRate: Double,
    durationMinutes: Double,
    isMale: Boolean
): Double {
    if (age <= 0 || weightKg <= 0 || averageHeartRate <= 0 || durationMinutes <= 0) {
        return 0.0
    }

    val caloriesBurned = if (isMale) {
        (age * 0.2017) + (weightKg * 0.199) + (averageHeartRate * 0.6309) - 55.0969
    } else {
        (age * 0.074) - (weightKg * 0.05741) + (averageHeartRate * 0.4472) - 20.4022
    }

    return caloriesBurned * durationMinutes / 4.184
}

@SuppressLint("RestrictedApi")
suspend fun sendWorkoutsToHealthConnect(
    workouts: List<Workout>,
    healthConnectClient: HealthConnectClient,
    workoutHistoryDao: WorkoutHistoryDao,
    updateAll: Boolean = false,
    age: Int,
    weightKg: Double,
) {
    if (workouts.isEmpty()) return

    val requiredPermissions = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class)
    )

    val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
    val missingPermissions = requiredPermissions - grantedPermissions

    if (missingPermissions.isNotEmpty()) {
        throw IllegalStateException("Missing required permissions: $missingPermissions")
    }

    val workoutsById = workouts.associateBy { it.id }

    val workoutHistories = if(updateAll){
        workoutHistoryDao.getAllWorkoutHistoriesByIsDone()
    }else {
        workoutHistoryDao.getWorkoutHistoriesByHasBeenSentToHealth(false)
    }.filter { workoutsById.containsKey(it.workoutId) }

    if (workoutHistories.isEmpty()) return

    // Process workout histories in batches of 5 to avoid exceeding Health Connect's 5MB chunk limit
    val batchSize = 5
    workoutHistories.chunked(batchSize).forEach { batch ->
        // Delete existing records for this batch
        healthConnectClient.deleteRecords(
            ExerciseSessionRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        healthConnectClient.deleteRecords(
            HeartRateRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        healthConnectClient.deleteRecords(
            TotalCaloriesBurnedRecord::class,
            clientRecordIdsList = batch.map { it.id.toString() },
            recordIdsList = emptyList()
        )

        // Create records for this batch
        val exerciseSessionRecords = batch.map {
            ExerciseSessionRecord(
                startTime = it.startTime.atZone(ZoneId.systemDefault()).toInstant(),
                startZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                endTime = it.startTime.plusSeconds(it.duration.toLong())
                    .atZone(ZoneId.systemDefault()).toInstant(),

                endZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                exerciseType = workoutsById[it.workoutId]!!.type,
                title = workoutsById[it.workoutId]!!.name,
                metadata = Metadata.activelyRecorded(
                    Device(type = Device.TYPE_WATCH),
                    clientRecordId = it.id.toString()
                ),
            )
        }

        val heartRateRecords = batch
            .filter { it.heartBeatRecords.isNotEmpty() }
            .mapNotNull { workoutHistory ->
                val startTime = workoutHistory.startTime.atZone(ZoneId.systemDefault()).toInstant()
                val endTime = workoutHistory.startTime.plusSeconds(workoutHistory.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
                val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

                val samples = workoutHistory.heartBeatRecords.mapIndexedNotNull { index, bpm ->
                    val sampleTime = startTime.plus(Duration.ofMillis(index.toLong() * 1000))
                    if (sampleTime.isAfter(endTime) || bpm <= 0) {
                        null
                    } else {
                        HeartRateRecord.Sample(
                            time = sampleTime,
                            beatsPerMinute = bpm.toLong()
                        )
                    }
                }

                if(samples.isEmpty()) {
                    return@mapNotNull null
                }

                HeartRateRecord(
                    startTime = startTime,
                    endTime = endTime,
                    startZoneOffset = zoneOffset,
                    endZoneOffset = zoneOffset,
                    samples = samples,
                    metadata = Metadata.activelyRecorded(
                        Device(type = Device.TYPE_WATCH),
                        clientRecordId =   workoutHistory.id.toString()
                    )
                )
            }

        val totalCaloriesBurnedRecords = batch
            .filter { it.heartBeatRecords.isNotEmpty() }
            .mapNotNull { workoutHistory ->
                val avgHeartRate = workoutHistory.heartBeatRecords.average()

                val durationMinutes = workoutHistory.duration.toDouble() / 60
                val kiloCaloriesBurned = calculateKiloCaloriesBurned(
                    age = age,
                    weightKg = weightKg.toDouble(),
                    averageHeartRate = avgHeartRate,
                    durationMinutes = durationMinutes,
                    isMale = true
                )

                if(kiloCaloriesBurned <= 0) {
                    return@mapNotNull null
                }

                val startTime = workoutHistory.startTime.atZone(ZoneId.systemDefault()).toInstant()
                val endTime = workoutHistory.startTime.plusSeconds(workoutHistory.duration.toLong()).atZone(ZoneId.systemDefault()).toInstant()
                val zoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now())

                androidx.health.connect.client.records.TotalCaloriesBurnedRecord(
                    startTime= startTime,
                    startZoneOffset = zoneOffset,
                    endTime = endTime,
                    endZoneOffset = zoneOffset,
                    energy = Energy.kilocalories(kiloCaloriesBurned),
                    metadata =  Metadata.activelyRecorded(
                        Device(type = Device.TYPE_WATCH),
                        clientRecordId = workoutHistory.id.toString()
                    )
                )
            }

        // Insert records for this batch
        healthConnectClient.insertRecords(exerciseSessionRecords)
        healthConnectClient.insertRecords(heartRateRecords)
        healthConnectClient.insertRecords(totalCaloriesBurnedRecords)

        // Update hasBeenSentToHealth flag for this batch
        for (workoutHistory in batch) {
            workoutHistoryDao.updateHasBeenSentToHealth(workoutHistory.id, true)
        }
    }
}

@SuppressLint("RestrictedApi")
suspend fun deleteWorkoutHistoriesFromHealthConnect(
    workoutHistories: List<WorkoutHistory>,
    healthConnectClient: HealthConnectClient
) {
    if (workoutHistories.isEmpty()) return

    val requiredPermissions = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class)
    )

    val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
    val missingPermissions = requiredPermissions - grantedPermissions

    if (missingPermissions.isNotEmpty()) {
        throw IllegalStateException("Missing required permissions: $missingPermissions")
    }

    healthConnectClient.deleteRecords(
        ExerciseSessionRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )

    healthConnectClient.deleteRecords(
        HeartRateRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )

    healthConnectClient.deleteRecords(
        TotalCaloriesBurnedRecord::class,
        clientRecordIdsList = workoutHistories.map { it.id.toString() },
        recordIdsList = emptyList()
    )
}

fun calculateVolume(weight: Double, reps: Int): Double {
    if(weight == 0.0) return reps.toDouble()
    return weight * reps
}

fun calculateOneRepMax(weight: Double, reps: Int): Double =
    weight * reps.toDouble().pow(0.10)

fun Double.round(decimals: Int): Double {
    var multiplier = 1.0
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
}

fun Float.round(decimals: Int): Float {
    var multiplier = 1.0f
    repeat(decimals) { multiplier *= 10 }
    return kotlin.math.round(this * multiplier) / multiplier
}

// Default height for the content fade gradient
private val DEFAULT_CONTENT_FADE_HEIGHT = 10.dp

@Composable
fun Modifier.verticalColumnScrollbar(
    scrollState: ScrollState,
    width: Dp = 4.dp,
    showScrollBarTrack: Boolean = true,
    scrollBarTrackColor: Color = DarkGray,
    scrollBarColor: Color = MediumLightGray,
    scrollBarCornerRadius: Float = 4f,
    endPadding: Float = 12f,
    trackHeight: Dp? = null,
    // Content fade effect parameters
    enableTopFade: Boolean = false,
    enableBottomFade: Boolean = false,
    contentFadeHeight: Dp = DEFAULT_CONTENT_FADE_HEIGHT,
    contentFadeColor: Color = DarkGray
): Modifier {
    // Remember updated state for all parameters accessed within draw lambda
    val rememberedShowTrack by rememberUpdatedState(showScrollBarTrack)
    val rememberedTrackColor by rememberUpdatedState(scrollBarTrackColor)
    val rememberedScrollBarColor by rememberUpdatedState(scrollBarColor)
    val rememberedWidth by rememberUpdatedState(width)
    val rememberedCornerRadius by rememberUpdatedState(scrollBarCornerRadius)
    val rememberedEndPadding by rememberUpdatedState(endPadding)
    val rememberedTrackHeight by rememberUpdatedState(trackHeight)
    val rememberedEnableTopFade by rememberUpdatedState(enableTopFade)
    val rememberedEnableBottomFade by rememberUpdatedState(enableBottomFade)
    val rememberedContentFadeHeight by rememberUpdatedState(contentFadeHeight)
    val rememberedContentFadeColor by rememberUpdatedState(contentFadeColor)

    return this.drawWithContent {
        // --- Draw the actual content first ---
        drawContent()

        // --- Content Fade Logic ---
        val fadeHeightPx = rememberedContentFadeHeight.toPx()
        val componentWidth = size.width
        val componentHeight = size.height
        val currentScrollValue = scrollState.value.toFloat()
        val maxScrollValue = scrollState.maxValue.toFloat()

        // Only proceed with fade drawing if fade height is positive
        if (fadeHeightPx > 0f) {

            // --- Top Fade Calculation ---
            if (rememberedEnableTopFade) {
                // Calculate alpha based on proximity to the top edge (within fadeHeightPx)
                // Alpha is 0.0 when scrollValue is 0, 1.0 when scrollValue >= fadeHeightPx
                val topAlpha = (currentScrollValue / fadeHeightPx).coerceIn(0f, 1f)

                // Only draw if alpha is > 0 (i.e., not exactly at the top)
                if (topAlpha > 0f) {
                    val topFadeBrush = Brush.verticalGradient(
                        colors = listOf(rememberedContentFadeColor, Color.Transparent),
                        startY = 0f,
                        endY = fadeHeightPx.coerceAtMost(componentHeight)
                    )
                    drawRect(
                        brush = topFadeBrush,
                        alpha = topAlpha,
                        topLeft = Offset.Zero,
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }

            // --- Bottom Fade Calculation ---
            if (rememberedEnableBottomFade && maxScrollValue > 0) { // Also check if scrolling is possible at all
                // Calculate distance from the bottom edge
                val distanceToBottom = maxScrollValue - currentScrollValue

                // Calculate alpha based on proximity to the bottom edge (within fadeHeightPx)
                // Alpha is 0.0 when distance is 0 (at bottom), 1.0 when distance >= fadeHeightPx
                val bottomAlpha = (distanceToBottom / fadeHeightPx).coerceIn(0f, 1f)

                // Only draw if alpha is > 0 (i.e., not exactly at the bottom)
                if (bottomAlpha > 0f) {
                    val bottomFadeBrush = Brush.verticalGradient(
                        colors = listOf(Color.Transparent, rememberedContentFadeColor),
                        startY = (componentHeight - fadeHeightPx).coerceAtLeast(0f),
                        endY = componentHeight
                    )
                    drawRect(
                        brush = bottomFadeBrush,
                        alpha = bottomAlpha,
                        topLeft = Offset(0f, (componentHeight - fadeHeightPx).coerceAtLeast(0f)),
                        size = Size(componentWidth, fadeHeightPx.coerceAtMost(componentHeight))
                    )
                }
            }
        }


        // --- Scrollbar Logic (remains the same, drawn on top) ---
        val viewportHeight = componentHeight
        val totalContentHeight = (maxScrollValue + viewportHeight).coerceAtLeast(viewportHeight)
        val scrollValue = currentScrollValue // Use already fetched value
        val visibleRatio = (viewportHeight / totalContentHeight).coerceIn(0f, 1f)

        if (visibleRatio >= 1f || maxScrollValue <= 0) {
            return@drawWithContent
        }

        val defaultTrackHeight = viewportHeight
        val actualTrackHeight = rememberedTrackHeight?.toPx()?.coerceAtMost(viewportHeight) ?: defaultTrackHeight
        val trackTopOffset = if (actualTrackHeight < viewportHeight) {
            (viewportHeight - actualTrackHeight) / 2f
        } else {
            0f
        }

        val minThumbHeight = rememberedWidth.toPx() * 2
        val scrollBarHeight = (visibleRatio * actualTrackHeight)
            .coerceAtLeast(minThumbHeight)
            .coerceAtMost(actualTrackHeight)
        val availableScrollSpace = maxScrollValue
        val availableTrackSpace = (actualTrackHeight - scrollBarHeight).coerceAtLeast(0f)
        val scrollProgress = if (availableScrollSpace > 0) scrollValue / availableScrollSpace else 0f
        val clampedScrollProgress = scrollProgress.coerceIn(0f, 1f)
        val scrollBarOffsetWithinTrack = clampedScrollProgress * availableTrackSpace
        val scrollBarTopOffset = trackTopOffset + scrollBarOffsetWithinTrack

        val cornerRadius = CornerRadius(rememberedCornerRadius)
        val barWidthPx = rememberedWidth.toPx()
        val paddingPx = rememberedEndPadding

        if (rememberedShowTrack) {
            drawRoundRect(
                color = rememberedTrackColor,
                topLeft = Offset(componentWidth - paddingPx - barWidthPx, trackTopOffset),
                size = Size(barWidthPx, actualTrackHeight),
                cornerRadius = cornerRadius
            )
        }

        drawRoundRect(
            color = rememberedScrollBarColor,
            topLeft = Offset(componentWidth - paddingPx - barWidthPx, scrollBarTopOffset),
            size = Size(barWidthPx, scrollBarHeight),
            cornerRadius = cornerRadius
        )
    }
}

fun ensureRestSeparatedBySets(components: List<com.gabstra.myworkoutassistant.shared.sets.Set>): List<com.gabstra.myworkoutassistant.shared.sets.Set> {
    val adjustedComponents = mutableListOf<Set>()
    var lastWasSet = false

    for (component in components) {
        if(component !is RestSet) {
            adjustedComponents.add(component)
            lastWasSet = true
        }else{
            if(lastWasSet){
                adjustedComponents.add(component)
            }

            lastWasSet = false
        }
    }
    return adjustedComponents
}

fun ensureRestSeparatedByExercises(components: List<WorkoutComponent>): List<WorkoutComponent> {
    val adjustedComponents = mutableListOf<WorkoutComponent>()
    var lastWasExercise = false

    for (component in components) {
        if (component !is Rest) {
            adjustedComponents.add(component)
            lastWasExercise = true
        } else {
            if (lastWasExercise) {
                //check if the next component if exist is exercise and enabled
                val nextComponentIndex = components.indexOf(component) + 1
                if (nextComponentIndex < components.size) {
                    val nextComponent = components[nextComponentIndex]
                    if (nextComponent.enabled) {
                        adjustedComponents.add(component)
                    } else {
                        adjustedComponents.add(component.copy(enabled = false))
                    }
                }
            }

            lastWasExercise = false
        }
    }
    return adjustedComponents
}

fun dateRangeFor(range: FilterRange): Pair<LocalDate, LocalDate> {
    val today = LocalDate.now()

    return when (range) {
        FilterRange.LAST_WEEK -> {
            val thisMonday = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY))
            val lastMonday = thisMonday.minusWeeks(1)
            val lastSunday = lastMonday.plusDays(6)
            lastMonday to lastSunday
        }
        FilterRange.LAST_7_DAYS -> {
            val start = today.minusDays(6)
            start to today
        }
        FilterRange.LAST_30_DAYS -> {
            val start = today.minusDays(29)
            start to today
        }
        FilterRange.THIS_MONTH -> {
            val ym = YearMonth.now()
            ym.atDay(1) to ym.atEndOfMonth()
        }
        FilterRange.LAST_3_MONTHS -> {
            val start = today.minusMonths(3)
            start to today
        }
        FilterRange.ALL -> LocalDate.MIN to LocalDate.MAX
    }
}

fun List<WorkoutHistory>.filterBy(range: FilterRange): List<WorkoutHistory> {
    val (start, end) = dateRangeFor(range)
    return this.filter { it.date >= start && it.date <= end }
}

@SuppressLint("SuspiciousModifierThen")
@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.repeatActionOnLongPressOrTap(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onAction: () -> Unit,
    onTap: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        var repeatedActionHappening = false
        detectTapGestures(
            onPress = { _ ->
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    do {
                        repeatedActionHappening = true
                        onAction()
                        delay(intervalMillis)
                    } while (true)
                }
                tryAwaitRelease()
                job.cancel()
                repeatedActionHappening = false
            },
            onTap = {
                if(!repeatedActionHappening) onTap()
            }
        )
    }
)

@SuppressLint("SuspiciousModifierThen")
@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.repeatActionOnLongPress(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onPressStart: () -> Unit,
    onBeforeLongPressRepeat: () -> Unit,
    onLongPressRepeat: () -> Unit,
    onRelease: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        detectTapGestures(
            onPress = { _ ->
                onPressStart()
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    onBeforeLongPressRepeat()
                    do {
                        delay(intervalMillis)
                        onLongPressRepeat()
                    } while (isActive)
                }

                tryAwaitRelease()
                job.cancel()
                onRelease()
            }
        )
    }
)

object Spacing {
    val xs = 6.dp
    val sm = 8.dp
    val md = 12.dp
    val lg = 16.dp
    val xl = 24.dp
}