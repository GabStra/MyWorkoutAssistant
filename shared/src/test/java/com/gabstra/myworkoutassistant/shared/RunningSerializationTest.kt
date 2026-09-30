package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.adapters.LocalDateAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalDateTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.LocalTimeAdapter
import com.gabstra.myworkoutassistant.shared.adapters.WorkoutHistoryAdapter
import com.gabstra.myworkoutassistant.shared.running.DistanceUnit
import com.gabstra.myworkoutassistant.shared.running.RunningEnvironment
import com.gabstra.myworkoutassistant.shared.running.RunningPrescription
import com.gabstra.myworkoutassistant.shared.running.RunningResult
import com.gabstra.myworkoutassistant.shared.running.RunningRoutePoint
import com.gabstra.myworkoutassistant.shared.running.RunningTargetType
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.google.gson.GsonBuilder
import com.google.gson.JsonParser
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class RunningSerializationTest {
    @Test
    fun workoutStoreRoundTripPreservesRunningPrescriptionAndDistanceUnit() {
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Run",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.RUNNING,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            runningPrescription = RunningPrescription(
                environment = RunningEnvironment.OUTDOOR,
                targetType = RunningTargetType.DISTANCE,
                targetValue = 5000.0
            )
        )
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "Run day",
            description = "",
            workoutComponents = listOf(exercise),
            order = 0,
            creationDate = LocalDate.of(2026, 9, 1),
            globalId = UUID.randomUUID(),
            type = 0
        )
        val store = WorkoutStore(
            birthDateYear = 1990,
            weightKg = 70.0,
            progressionPercentageAmount = 2.5,
            workouts = listOf(workout),
            distanceUnit = DistanceUnit.MILES
        )

        val roundTripped = fromJSONToWorkoutStore(fromWorkoutStoreToJSON(store))

        assertEquals(DistanceUnit.MILES, roundTripped.distanceUnit)
        val run = roundTripped.workouts.single().workoutComponents.single() as Exercise
        assertEquals(ExerciseType.RUNNING, run.exerciseType)
        assertEquals(RunningPrescription(RunningEnvironment.OUTDOOR, RunningTargetType.DISTANCE, 5000.0), run.runningPrescription)
    }

    @Test
    fun workoutHistoryRoundTripPreservesRunMetricsAndRouteAndOldRowsDefaultEmpty() {
        val gson = GsonBuilder()
            .registerTypeAdapter(LocalDate::class.java, LocalDateAdapter())
            .registerTypeAdapter(LocalTime::class.java, LocalTimeAdapter())
            .registerTypeAdapter(LocalDateTime::class.java, LocalDateTimeAdapter())
            .registerTypeAdapter(WorkoutHistory::class.java, WorkoutHistoryAdapter())
            .create()
        val history = WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            date = LocalDate.of(2026, 9, 29),
            time = LocalTime.of(12, 0),
            startTime = LocalDateTime.of(2026, 9, 29, 11, 30),
            duration = 1800,
            heartBeatRecords = listOf(120, 150),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID(),
            runningResults = listOf(
                RunningResult(
                    exerciseId = UUID.randomUUID().toString(),
                    elapsedTimeMillis = 1_200_000,
                    distanceMeters = 5000.0,
                    averagePaceSecondsPerKilometer = 240.0,
                    averageHeartRateBpm = 145,
                    minHeartRateBpm = 110,
                    maxHeartRateBpm = 170,
                    route = listOf(RunningRoutePoint(41.9, 12.5, 0), RunningRoutePoint(41.91, 12.51, 1_200_000))
                )
            )
        )

        val parsed = gson.fromJson(gson.toJson(history), WorkoutHistory::class.java)
        assertEquals(history.runningResults, parsed.runningResults)

        val oldJsonElement = JsonParser.parseString(gson.toJson(history)).asJsonObject
        oldJsonElement.remove("runningResults")
        val oldJson = oldJsonElement.toString()
        val oldRecord = gson.fromJson(oldJson, WorkoutHistory::class.java)
        assertTrue(oldRecord.runningResults.isEmpty())
    }
}
