package com.gabstra.myworkoutassistant.shared.motion

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.HeartRateSource
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import java.time.LocalDate
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class MotionCaptureLabelMapperTest {
    @Test
    fun `set state maps to exercise label`() {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val workout = workoutWithExercise(exerciseId = exerciseId)
        val state = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(id = setId, reps = 5, weight = 100.0),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(
                WeightSetData(actualReps = 5, actualWeight = 100.0, volume = 500.0)
            ),
            hasNoHistory = true,
            skipped = false,
            currentBodyWeight = 80.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null
        )

        val label = MotionCaptureLabelMapper.map(state, workout)

        assertEquals(MotionCaptureLabelKind.EXERCISE, label?.kind)
        assertEquals(exerciseId, label?.exerciseId)
        assertEquals(setId, label?.setId)
        assertEquals(ExerciseType.WEIGHT, label?.exerciseType)
    }

    @Test
    fun `rest in superset preserves active exercise superset metadata`() {
        val supersetId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val workout = workoutWithSuperset(supersetId = supersetId, exerciseId = exerciseId)
        val state = WorkoutState.Rest(
            set = RestSet(id = UUID.randomUUID(), timeInSeconds = 30),
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(startTimer = 30, endTimer = 30)),
            exerciseId = exerciseId
        )

        val label = MotionCaptureLabelMapper.map(state, workout)

        assertEquals(MotionCaptureLabelKind.REST, label?.kind)
        assertEquals(exerciseId, label?.exerciseId)
        assertEquals(supersetId, label?.supersetId)
    }

    @Test
    fun `timed exercise label is marked as no rep expected`() {
        val exerciseId = UUID.randomUUID()
        val workout = Workout(
            id = UUID.randomUUID(),
            name = "Workout",
            description = "",
            workoutComponents = listOf(
                Exercise(
                    id = exerciseId,
                    enabled = true,
                    name = "Run",
                    notes = "",
                    sets = listOf(
                        EnduranceSet(
                            id = UUID.randomUUID(),
                            timeInMillis = 60_000,
                            autoStart = true,
                            autoStop = true
                        )
                    ),
                    exerciseType = ExerciseType.COUNTUP,
                    minReps = 0,
                    maxReps = 0,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = null,
                    bodyWeightPercentage = null
                )
            ),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.now(),
            globalId = UUID.randomUUID(),
            type = 0
        )
        val state = WorkoutState.Set(
            exerciseId = exerciseId,
            set = EnduranceSet(
                id = UUID.randomUUID(),
                timeInMillis = 60_000,
                autoStart = true,
                autoStop = true
            ),
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(
                EnduranceSetData(
                    startTimer = 60_000,
                    endTimer = 59_000,
                    autoStart = true,
                    autoStop = true
                )
            ),
            hasNoHistory = true,
            skipped = false,
            currentBodyWeight = 80.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null
        )

        val label = MotionCaptureLabelMapper.map(state, workout)

        assertEquals(ExerciseType.COUNTUP, label?.exerciseType)
        assertEquals(true, label?.noRepExpected)
    }

    @Test
    fun `preparing state is ignored`() {
        val workout = workoutWithExercise(exerciseId = UUID.randomUUID())
        assertNull(MotionCaptureLabelMapper.map(WorkoutState.Preparing(dataLoaded = true), workout))
    }

    private fun workoutWithExercise(exerciseId: UUID): Workout =
        Workout(
            id = UUID.randomUUID(),
            name = "Workout",
            description = "",
            workoutComponents = listOf(
                Exercise(
                    id = exerciseId,
                    enabled = true,
                    name = "Squat",
                    notes = "",
                    sets = listOf(WeightSet(id = UUID.randomUUID(), reps = 5, weight = 100.0)),
                    exerciseType = ExerciseType.WEIGHT,
                    minReps = 5,
                    maxReps = 5,
                    lowerBoundMaxHRPercent = null,
                    upperBoundMaxHRPercent = null,
                    equipmentId = null,
                    bodyWeightPercentage = null
                )
            ),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.now(),
            globalId = UUID.randomUUID(),
            type = 0
        )

    private fun workoutWithSuperset(supersetId: UUID, exerciseId: UUID): Workout =
        Workout(
            id = UUID.randomUUID(),
            name = "Superset",
            description = "",
            workoutComponents = listOf(
                Superset(
                    id = supersetId,
                    enabled = true,
                    exercises = listOf(
                        Exercise(
                            id = exerciseId,
                            enabled = true,
                            name = "Row",
                            notes = "",
                            sets = listOf(WeightSet(id = UUID.randomUUID(), reps = 8, weight = 60.0)),
                            exerciseType = ExerciseType.WEIGHT,
                            minReps = 8,
                            maxReps = 8,
                            lowerBoundMaxHRPercent = null,
                            upperBoundMaxHRPercent = null,
                            equipmentId = null,
                            bodyWeightPercentage = null
                        )
                    ),
                    restSecondsByExercise = mapOf(exerciseId to 20)
                )
            ),
            order = 0,
            enabled = true,
            heartRateSource = HeartRateSource.WATCH_SENSOR,
            creationDate = LocalDate.now(),
            globalId = UUID.randomUUID(),
            type = 0
        )
}
