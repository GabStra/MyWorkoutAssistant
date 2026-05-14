package com.gabstra.myworkoutassistant.shared.workout.recovery

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.ExerciseChildItem
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateContainer
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateSequenceItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import java.util.UUID

class WorkoutRecoverySnapshotCodecTest {

    @Test
    fun decode_preservesPreviousSetDataForResumedWeightSet() {
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val baseline = WeightSetData(
            actualReps = 8,
            actualWeight = 50.0,
            volume = 400.0,
            subCategory = SetSubCategory.WorkSet
        )
        val resumed = WeightSetData(
            actualReps = 8,
            actualWeight = 55.0,
            volume = 440.0,
            subCategory = SetSubCategory.WorkSet
        )
        val sequence = listOf(
            WorkoutStateSequenceItem.Container(
                WorkoutStateContainer.ExerciseState(
                    exerciseId = exerciseId,
                    childItems = mutableListOf(
                        ExerciseChildItem.Normal(
                            WorkoutState.Set(
                                exerciseId = exerciseId,
                                set = WeightSet(
                                    id = setId,
                                    reps = 8,
                                    weight = 50.0,
                                    subCategory = SetSubCategory.WorkSet
                                ),
                                setIndex = 0u,
                                previousSetData = baseline,
                                currentSetDataState = mutableStateOf(resumed),
                                historicalSetData = baseline,
                                hasNoHistory = false,
                                startTime = null,
                                skipped = false,
                                lowerBoundMaxHRPercent = null,
                                upperBoundMaxHRPercent = null,
                                currentBodyWeight = 0.0,
                                plateChangeResult = null,
                                streak = 0,
                                progressionState = ProgressionState.PROGRESS,
                                isWarmupSet = false,
                                equipmentId = null
                            )
                        )
                    )
                )
            )
        )

        val encoded = WorkoutRecoverySnapshotCodec.encode(
            workoutId = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            currentIndex = 0,
            sequenceItems = sequence
        )

        val decoded = WorkoutRecoverySnapshotCodec.decode(encoded)
        val decodedSet = (((decoded?.sequenceItems?.singleOrNull() as? WorkoutStateSequenceItem.Container)
            ?.container as? WorkoutStateContainer.ExerciseState)
            ?.childItems?.singleOrNull() as? ExerciseChildItem.Normal)
            ?.state as? WorkoutState.Set

        assertNotNull(decodedSet)
        val previous = decodedSet?.previousSetData as? WeightSetData
        val current = decodedSet?.currentSetData as? WeightSetData

        assertNotNull(previous)
        assertNotNull(current)
        assertEquals(50.0, previous?.actualWeight ?: 0.0, 0.0)
        assertEquals(55.0, current?.actualWeight ?: 0.0, 0.0)
    }
}
