package com.gabstra.myworkoutassistant.shared.workout.assembly

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class WorkoutSetStateFactoryTest {

    @Test
    fun `superset preview uses runtime assembly order and omits trailing rest`() {
        val firstExercise = createExercise("Press", null).copy(
            sets = listOf(createWeightSet(), createWeightSet())
        )
        val secondExercise = createExercise("Row", null).copy(
            sets = listOf(createWeightSet(), createWeightSet())
        )
        val superset = Superset(
            id = UUID.randomUUID(),
            enabled = true,
            exercises = listOf(firstExercise, secondExercise),
            restSecondsByExercise = mapOf(firstExercise.id to 15, secondExercise.id to 60)
        )

        val states = WorkoutSupersetAssemblyService().assemblePreviewChildStates(superset)

        assertEquals(
            listOf(
                firstExercise.id,
                firstExercise.id,
                secondExercise.id,
                secondExercise.id,
                firstExercise.id,
                firstExercise.id,
                secondExercise.id
            ),
            states.map { state ->
                when (state) {
                    is WorkoutState.Set -> state.exerciseId
                    is WorkoutState.Rest -> state.exerciseId
                    else -> error("Unexpected state: $state")
                }
            }
        )
        assertEquals(
            listOf(15, 60, 15),
            states.filterIsInstance<WorkoutState.Rest>().map { (it.set as RestSet).timeInSeconds }
        )
    }

    @Test
    fun `prepared superset preview inserts calibration for exercises that require it`() {
        val calibrationExercise = createExercise("Press", null).copy(
            requiresLoadCalibration = true,
            sets = listOf(createWeightSet())
        )
        val regularExercise = createExercise("Row", null).copy(
            sets = listOf(createWeightSet())
        )
        val superset = Superset(
            id = UUID.randomUUID(),
            enabled = true,
            exercises = listOf(calibrationExercise, regularExercise),
            restSecondsByExercise = emptyMap()
        )

        val states = WorkoutSupersetAssemblyService().assemblePreparedPreviewChildStates(
            superset = superset,
            bodyWeightKg = 0.0,
            getEquipmentById = { null },
            getAvailableTotals = { emptySet() }
        )

        val calibrationStates = states
            .filterIsInstance<WorkoutState.Set>()
            .filter { it.exerciseId == calibrationExercise.id }

        assertEquals(2, calibrationStates.size)
        assertTrue(calibrationStates.first().isCalibrationSet)
        assertTrue(!calibrationStates.last().isCalibrationSet)
    }

    @Test
    fun `superset keeps a unilateral set and its intra-set rest together`() {
        val factory = WorkoutSetStateFactory()
        val unilateralExercise = createExercise("Split squat", intraSetRestInSeconds = 30)
        val normalExercise = createExercise("Row", intraSetRestInSeconds = null)
        val unilateralSet = createSetState(unilateralExercise)
        val normalSet = createSetState(normalExercise)
        val unilateralBlock = factory.buildUnilateralSetBlock(
            exercise = unilateralExercise,
            setState = unilateralSet,
            setIndex = 1
        ) as ExerciseChildItem.UnilateralSetBlock

        val states = WorkoutSupersetAssemblyService().assembleSupersetChildStates(
            superset = Superset(
                id = UUID.randomUUID(),
                enabled = true,
                exercises = listOf(unilateralExercise, normalExercise),
                restSecondsByExercise = emptyMap()
            ),
            queues = listOf(
                unilateralBlock.childStates.toMutableList(),
                mutableListOf(normalSet)
            )
        )

        assertEquals(
            listOf(
                unilateralSet.set.id,
                (unilateralBlock.childStates[1] as WorkoutState.Rest).set.id,
                unilateralSet.set.id,
                normalSet.set.id
            ),
            states.map {
                when (it) {
                    is WorkoutState.Set -> it.set.id
                    is WorkoutState.Rest -> it.set.id
                    else -> error("Unexpected state: $it")
                }
            }
        )
    }

    @Test
    fun `superset keeps calibration load selection before work rounds`() {
        val calibrationExercise = createExercise("Calibration press", intraSetRestInSeconds = null)
        val normalExercise = createExercise("Row", intraSetRestInSeconds = null)
        val calibrationSelection = createCalibrationLoadSelection(calibrationExercise)
        val calibrationWorkSet = createSetState(calibrationExercise)
        val normalWorkSet = createSetState(normalExercise)

        val states = WorkoutSupersetAssemblyService().assembleSupersetChildStates(
            superset = Superset(
                id = UUID.randomUUID(),
                enabled = true,
                exercises = listOf(calibrationExercise, normalExercise),
                restSecondsByExercise = emptyMap()
            ),
            queues = listOf(
                mutableListOf(calibrationSelection, calibrationWorkSet),
                mutableListOf(normalWorkSet)
            )
        )

        assertEquals(
            listOf(calibrationSelection, calibrationWorkSet, normalWorkSet),
            states
        )
    }

    @Test
    fun `buildUnilateralSetBlock creates distinct states for each side`() {
        val factory = WorkoutSetStateFactory()
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Dumbbell Curl",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 8,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            requiresLoadCalibration = false,
            intraSetRestInSeconds = 30
        )
        val setState = WorkoutState.Set(
            exerciseId = exercise.id,
            set = WeightSet(
                id = UUID.randomUUID(),
                reps = 10,
                weight = 12.5,
                subCategory = SetSubCategory.WorkSet
            ),
            setIndex = 1u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(
                WeightSetData(
                    actualReps = 10,
                    actualWeight = 12.5,
                    volume = 125.0
                )
            ),
            hasNoHistory = true,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null
        )

        val block = factory.buildUnilateralSetBlock(
            exercise = exercise,
            setState = setState,
            setIndex = 1
        ) as ExerciseChildItem.UnilateralSetBlock

        val firstSide = block.childStates[0] as WorkoutState.Set
        val rest = block.childStates[1] as WorkoutState.Rest
        val secondSide = block.childStates[2] as WorkoutState.Set

        assertTrue(firstSide.isUnilateral)
        assertTrue(secondSide.isUnilateral)
        assertEquals(1u, firstSide.intraSetCounter)
        assertEquals(2u, secondSide.intraSetCounter)
        assertNotSame(firstSide, secondSide)
        assertSame(secondSide, rest.nextState)
    }

    private fun createExercise(name: String, intraSetRestInSeconds: Int?): Exercise = Exercise(
        id = UUID.randomUUID(),
        enabled = true,
        name = name,
        notes = "",
        sets = emptyList(),
        exerciseType = ExerciseType.WEIGHT,
        minReps = 8,
        maxReps = 12,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        generateWarmUpSets = false,
        keepScreenOn = false,
        showCountDownTimer = false,
        requiresLoadCalibration = false,
        intraSetRestInSeconds = intraSetRestInSeconds
    )

    private fun createSetState(exercise: Exercise): WorkoutState.Set = WorkoutState.Set(
        exerciseId = exercise.id,
        set = WeightSet(
            id = UUID.randomUUID(),
            reps = 10,
            weight = 12.5,
            subCategory = SetSubCategory.WorkSet
        ),
        setIndex = 1u,
        previousSetData = null,
        currentSetDataState = mutableStateOf(
            WeightSetData(
                actualReps = 10,
                actualWeight = 12.5,
                volume = 125.0
            )
        ),
        hasNoHistory = true,
        skipped = false,
        currentBodyWeight = 0.0,
        streak = 0,
        progressionState = null,
        isWarmupSet = false,
        equipmentId = null
    )

    private fun createWeightSet(): WeightSet = WeightSet(
        id = UUID.randomUUID(),
        reps = 10,
        weight = 12.5,
        subCategory = SetSubCategory.WorkSet
    )

    private fun createCalibrationLoadSelection(exercise: Exercise): WorkoutState.CalibrationLoadSelection {
        val calibrationSet = WeightSet(
            id = UUID.randomUUID(),
            reps = 10,
            weight = 0.0,
            subCategory = SetSubCategory.CalibrationSet
        )
        return WorkoutState.CalibrationLoadSelection(
            exerciseId = exercise.id,
            calibrationSet = calibrationSet,
            setIndex = 0u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(
                WeightSetData(
                    actualReps = 10,
                    actualWeight = 0.0,
                    volume = 0.0
                )
            ),
            equipmentId = null,
            currentBodyWeight = 0.0
        )
    }
}
