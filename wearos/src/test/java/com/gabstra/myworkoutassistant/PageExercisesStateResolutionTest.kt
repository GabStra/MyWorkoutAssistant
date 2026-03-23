package com.gabstra.myworkoutassistant

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.text.AnnotatedString
import com.gabstra.myworkoutassistant.composables.PageExercisesItem
import com.gabstra.myworkoutassistant.composables.buildPageExercisesItems
import com.gabstra.myworkoutassistant.composables.resolvePageExercisesActiveState
import com.gabstra.myworkoutassistant.composables.resolvePageExercisesItemIndex
import com.gabstra.myworkoutassistant.composables.resolvePageExercisesDisplayCounter
import com.gabstra.myworkoutassistant.composables.resolvePageExercisesCurrentItemIndex
import com.gabstra.myworkoutassistant.composables.toExerciseSetDisplayRowOrNull
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.screens.setCurrentWorkoutState
import com.gabstra.myworkoutassistant.screens.setFieldValue
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateMachine
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.UUID

class PageExercisesStateResolutionTest {

    @Test
    fun `intra exercise rest state resolves to next executable state for exercises page`() {
        val upcomingSetState = createSetState()
        val restState = createRestState(nextState = upcomingSetState)

        val resolvedState = resolvePageExercisesActiveState(workoutState = restState)

        assertSame(upcomingSetState, resolvedState)
    }

    @Test
    fun `rest state falls back to provided set state when next state is missing`() {
        val fallbackSetState = createSetState()
        val restState = createRestState(nextState = null)

        val resolvedState = resolvePageExercisesActiveState(
            workoutState = restState,
            fallbackSetState = fallbackSetState
        )

        assertSame(fallbackSetState, resolvedState)
    }

    @Test
    fun `rest between exercises remains current state for exercises page`() {
        val upcomingSetState = createSetState()
        val interExerciseRestState = createRestState(
            exerciseId = null,
            nextState = upcomingSetState
        )

        val resolvedState = resolvePageExercisesActiveState(workoutState = interExerciseRestState)

        assertSame(interExerciseRestState, resolvedState)
    }

    @Test
    fun `rest states are included in exercise display rows`() {
        val restState = createRestState(nextState = null)

        val displayRow = toExerciseSetDisplayRowOrNull(restState)

        assertNotNull(displayRow)
    }

    @Test
    fun `non rest state remains unchanged`() {
        val setState = createSetState()

        val resolvedState = resolvePageExercisesActiveState(workoutState = setState)

        assertSame(setState, resolvedState)
    }

    @Test
    fun `page exercises inserts rest page between exercise containers`() {
        val firstExercise = createExercise(name = "Bench Press")
        val secondExercise = createExercise(name = "Row")
        val firstSet = createSetState(exerciseId = firstExercise.id)
        val secondSet = createSetState(exerciseId = secondExercise.id)
        val restState = createRestState(exerciseId = null, nextState = secondSet)
        val viewModel = createViewModelWithSequence(
            exercises = listOf(firstExercise, secondExercise),
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = firstExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(firstSet))
                    )
                ),
                WorkoutStateSequenceItem.RestBetweenExercises(restState),
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = secondExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(secondSet))
                    )
                )
            ),
            currentState = restState
        )

        val items = buildPageExercisesItems(viewModel)

        assertEquals(3, items.size)
        assertEquals(PageExercisesItem.ExercisePage(firstExercise), items[0])
        assertTrue(items[1] is PageExercisesItem.RestPage)
        assertEquals(PageExercisesItem.ExercisePage(secondExercise), items[2])
        val restPage = items[1] as PageExercisesItem.RestPage
        assertEquals(AnnotatedString(firstExercise.name), restPage.previousDisplayName)
        assertEquals(AnnotatedString(secondExercise.name), restPage.nextDisplayName)
    }

    @Test
    fun `current item index points to inter exercise rest page when active`() {
        val firstExercise = createExercise(name = "Bench Press")
        val secondExercise = createExercise(name = "Row")
        val firstSet = createSetState(exerciseId = firstExercise.id)
        val secondSet = createSetState(exerciseId = secondExercise.id)
        val restState = createRestState(exerciseId = null, nextState = secondSet)
        val viewModel = createViewModelWithSequence(
            exercises = listOf(firstExercise, secondExercise),
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = firstExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(firstSet))
                    )
                ),
                WorkoutStateSequenceItem.RestBetweenExercises(restState),
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = secondExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(secondSet))
                    )
                )
            ),
            currentState = restState
        )
        val items = buildPageExercisesItems(viewModel)

        val index = resolvePageExercisesCurrentItemIndex(
            items = items,
            workoutState = restState,
            fallbackSetState = secondSet,
            viewModel = viewModel
        )

        assertEquals(1, index)
    }

    @Test
    fun `selected next exercise is reachable while inter exercise rest is active`() {
        val firstExercise = createExercise(name = "Bench Press")
        val secondExercise = createExercise(name = "Row")
        val firstSet = createSetState(exerciseId = firstExercise.id)
        val secondSet = createSetState(exerciseId = secondExercise.id)
        val restState = createRestState(exerciseId = null, nextState = secondSet)
        val viewModel = createViewModelWithSequence(
            exercises = listOf(firstExercise, secondExercise),
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = firstExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(firstSet))
                    )
                ),
                WorkoutStateSequenceItem.RestBetweenExercises(restState),
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = secondExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(secondSet))
                    )
                )
            ),
            currentState = restState
        )
        val items = buildPageExercisesItems(viewModel)

        val index = resolvePageExercisesItemIndex(
            items = items,
            selectedExercise = secondExercise,
            viewModel = viewModel
        )

        assertEquals(2, index)
    }

    @Test
    fun `display counter excludes inter exercise rest pages`() {
        val firstExercise = createExercise(name = "Bench Press")
        val secondExercise = createExercise(name = "Row")
        val firstSet = createSetState(exerciseId = firstExercise.id)
        val secondSet = createSetState(exerciseId = secondExercise.id)
        val restState = createRestState(exerciseId = null, nextState = secondSet)
        val viewModel = createViewModelWithSequence(
            exercises = listOf(firstExercise, secondExercise),
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = firstExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(firstSet))
                    )
                ),
                WorkoutStateSequenceItem.RestBetweenExercises(restState),
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = secondExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(secondSet))
                    )
                )
            ),
            currentState = restState
        )
        val items = buildPageExercisesItems(viewModel)

        val counter = resolvePageExercisesDisplayCounter(
            items = items,
            selectedPageIndex = 1
        )

        assertEquals("2/2", counter)
    }

    @Test
    fun `rest page uses superset page naming for next container`() {
        val firstExercise = createExercise(name = "Bench Press")
        val supersetFirst = createExercise(name = "Curl")
        val supersetSecond = createExercise(name = "Tricep Extension")
        val firstSet = createSetState(exerciseId = firstExercise.id)
        val supersetSet = createSetState(exerciseId = supersetFirst.id)
        val restState = createRestState(exerciseId = null, nextState = supersetSet)
        val supersetId = UUID.randomUUID()
        val viewModel = createViewModelWithSequence(
            exercises = listOf(firstExercise, supersetFirst, supersetSecond),
            sequence = listOf(
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.ExerciseState(
                        exerciseId = firstExercise.id,
                        childItems = mutableListOf(ExerciseChildItem.Normal(firstSet))
                    )
                ),
                WorkoutStateSequenceItem.RestBetweenExercises(restState),
                WorkoutStateSequenceItem.Container(
                    WorkoutStateContainer.SupersetState(
                        supersetId = supersetId,
                        childStates = mutableListOf(supersetSet)
                    )
                )
            ),
            currentState = restState,
            supersetIdByExerciseId = mapOf(
                supersetFirst.id to supersetId,
                supersetSecond.id to supersetId
            ),
            exercisesBySupersetId = mapOf(supersetId to listOf(supersetFirst, supersetSecond))
        )

        val items = buildPageExercisesItems(viewModel)
        val restPage = items[1] as PageExercisesItem.RestPage

        assertEquals(AnnotatedString(firstExercise.name), restPage.previousDisplayName)
        assertEquals(
            AnnotatedString("Curl (A) ↔ Tricep Extension (B)"),
            restPage.nextDisplayName
        )
    }

    private fun createViewModelWithSequence(
        exercises: List<Exercise>,
        sequence: List<WorkoutStateSequenceItem>,
        currentState: WorkoutState,
        supersetIdByExerciseId: Map<UUID, UUID> = emptyMap(),
        exercisesBySupersetId: Map<UUID, List<Exercise>> = emptyMap(),
    ): AppViewModel {
        val viewModel = AppViewModel()
        viewModel.exercisesById = exercises.associateBy { it.id }
        viewModel.supersetIdByExerciseId = supersetIdByExerciseId
        viewModel.exercisesBySupersetId = exercisesBySupersetId
        val stateMachine = WorkoutStateMachine.fromSequence(sequence, startIndex = sequence
            .flatMap { item ->
                when (item) {
                    is WorkoutStateSequenceItem.Container -> when (val container = item.container) {
                        is WorkoutStateContainer.ExerciseState -> container.childItems.flatMap { childItem ->
                            when (childItem) {
                                is ExerciseChildItem.Normal -> listOf(childItem.state)
                                is ExerciseChildItem.CalibrationExecutionBlock -> childItem.childStates
                                is ExerciseChildItem.LoadSelectionBlock -> childItem.childStates
                                is ExerciseChildItem.UnilateralSetBlock -> childItem.childStates
                            }
                        }
                        is WorkoutStateContainer.SupersetState -> container.childStates
                    }
                    is WorkoutStateSequenceItem.RestBetweenExercises -> listOf(item.rest)
                }
            }.indexOf(currentState))
        setFieldValue(viewModel, "stateMachine", stateMachine)
        setCurrentWorkoutState(viewModel, currentState)
        return viewModel
    }

    private fun createExercise(
        id: UUID = UUID.randomUUID(),
        name: String,
    ): Exercise {
        return Exercise(
            id = id,
            enabled = true,
            name = name,
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minLoadPercent = 0.0,
            maxLoadPercent = 0.0,
            minReps = 6,
            maxReps = 10,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            generateWarmUpSets = false,
            keepScreenOn = false,
            showCountDownTimer = false,
            requiresLoadCalibration = false
        )
    }

    private fun createSetState(exerciseId: UUID = UUID.randomUUID()): WorkoutState.Set {
        val setData = WeightSetData(
            actualReps = 8,
            actualWeight = 60.0,
            volume = 480.0
        )
        return WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(
                id = UUID.randomUUID(),
                reps = 8,
                weight = 60.0,
                subCategory = SetSubCategory.WorkSet
            ),
            setIndex = 1u,
            previousSetData = setData,
            currentSetDataState = mutableStateOf(setData),
            hasNoHistory = false,
            skipped = false,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false,
            equipmentId = null
        )
    }

    private fun createRestState(
        nextState: WorkoutState?,
        exerciseId: UUID? = UUID.randomUUID(),
    ): WorkoutState.Rest {
        return WorkoutState.Rest(
            set = RestSet(
                id = UUID.randomUUID(),
                timeInSeconds = 90,
                subCategory = SetSubCategory.WorkSet
            ),
            order = 2u,
            currentSetDataState = mutableStateOf(
                RestSetData(
                    startTimer = 90,
                    endTimer = 90
                )
            ),
            exerciseId = exerciseId,
            nextState = nextState
        )
    }
}
