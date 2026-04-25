package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ProgressionMode
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.RestHistoryScope
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class SessionHeartRateMarkdownTest {

    @Test
    fun appendExerciseHeartRateMarkdown_includesDurationForSampledIntervals() {
        val startTime = LocalDateTime.of(2026, 4, 1, 9, 0, 0)
        val workoutHistory = WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            date = startTime.toLocalDate(),
            time = startTime.toLocalTime(),
            startTime = startTime,
            duration = 300,
            heartBeatRecords = listOf(120, 122, 124, 126, 128, 130, 132, 134, 136, 138),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID()
        )
        val exerciseId = UUID.randomUUID()
        val setHistories = listOf(
            SetHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistory.id,
                exerciseId = exerciseId,
                equipmentIdSnapshot = null,
                equipmentNameSnapshot = null,
                equipmentTypeSnapshot = null,
                setId = UUID.randomUUID(),
                order = 0u,
                startTime = startTime,
                endTime = startTime.plusSeconds(4),
                setData = WeightSetData(actualReps = 8, actualWeight = 40.0, volume = 320.0),
                skipped = false
            )
        )
        val restsForExercise = listOf(
            RestHistory(
                id = UUID.randomUUID(),
                workoutHistoryId = workoutHistory.id,
                scope = RestHistoryScope.INTRA_EXERCISE,
                executionSequence = 1u,
                setData = RestSetData(startTimer = 3, endTimer = 0),
                startTime = startTime.plusSeconds(4),
                endTime = startTime.plusSeconds(7),
                workoutComponentId = null,
                exerciseId = exerciseId,
                restSetId = UUID.randomUUID(),
                order = 1u
            )
        )
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Bench Press",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 70.0,
            maxLoadPercent = 85.0,
            minReps = 6,
            maxReps = 10,
            lowerBoundMaxHRPercent = 0.65f,
            upperBoundMaxHRPercent = 0.85f,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null
        )
        val workoutStore = WorkoutStore(
            workouts = emptyList(),
            equipments = emptyList(),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 2.5,
            measuredMaxHeartRate = 190,
            restingHeartRate = 55
        )

        val markdown = StringBuilder()
        appendExerciseHeartRateMarkdown(
            markdown = markdown,
            workoutHistory = workoutHistory,
            setHistories = setHistories,
            restsForExercise = restsForExercise,
            userAge = 36,
            workoutStore = workoutStore,
            exerciseForTargetBand = exercise
        )

        val rendered = markdown.toString()
        assertTrue(rendered.contains("#### Exercise Heart Rate"))
        assertTrue(rendered.contains("- Duration: 00:07"))
        assertTrue(rendered.contains("- Zone time:"))
        assertTrue(rendered.contains("- Target band:"))
    }

    @Test
    fun appendSessionHeartRateMarkdown_includesDuration() {
        val startTime = LocalDateTime.of(2026, 4, 1, 10, 0, 0)
        val workoutHistory = WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            date = LocalDate.of(2026, 4, 1),
            time = LocalTime.of(10, 0),
            startTime = startTime,
            duration = 120,
            heartBeatRecords = listOf(118, 119, 120, 121, 122),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID()
        )
        val workoutStore = WorkoutStore(
            workouts = emptyList(),
            equipments = emptyList(),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 2.5,
            measuredMaxHeartRate = 190,
            restingHeartRate = 55
        )
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Run",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.COUNTUP,
            minLoadPercent = 0.0,
            maxLoadPercent = 0.0,
            minReps = 0,
            maxReps = 0,
            lowerBoundMaxHRPercent = 0.6f,
            upperBoundMaxHRPercent = 0.8f,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            progressionMode = ProgressionMode.DOUBLE_PROGRESSION,
            keepScreenOn = false,
            showCountDownTimer = false,
            intraSetRestInSeconds = null
        )

        val markdown = StringBuilder()
        appendSessionHeartRateMarkdown(
            markdown = markdown,
            workoutHistory = workoutHistory,
            userAge = 36,
            workoutStore = workoutStore,
            exerciseForTargetBand = exercise
        )

        val rendered = markdown.toString()
        assertTrue(rendered.contains("#### Session Heart Rate"))
        assertTrue(rendered.contains("- Duration: 00:05"))
        assertTrue(rendered.contains("- Zone time:"))
    }
}
