package com.gabstra.myworkoutassistant.shared.workout.persistence

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutStateQueries
import java.util.UUID
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WorkoutSetHistoryOpsTest {

    private val exerciseId = UUID.randomUUID()

    @Test
    fun shouldSkipPersistingState_skipsRest() {
        val restSet = RestSet(UUID.randomUUID(), 90, SetSubCategory.WorkSet)
        val restState = WorkoutState.Rest(
            set = restSet,
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90, SetSubCategory.WorkSet)),
            exerciseId = exerciseId,
            isIntraSetRest = false
        )
        assertTrue(
            WorkoutSetHistoryOps.shouldSkipPersistingState(
                restState,
                emptyMap()
            )
        )
    }

    @Test
    fun buildSetHistory_returnsNullForRest() {
        val restSet = RestSet(UUID.randomUUID(), 90, SetSubCategory.WorkSet)
        val restState = WorkoutState.Rest(
            set = restSet,
            order = 0u,
            currentSetDataState = mutableStateOf(RestSetData(90, 90, SetSubCategory.WorkSet)),
            exerciseId = exerciseId,
            isIntraSetRest = false
        )
        assertNull(
            WorkoutSetHistoryOps.buildSetHistory(
                restState,
                WorkoutStateQueries.StateHistoryIdentity(
                    setId = UUID.randomUUID(),
                    order = 0u,
                    exerciseId = exerciseId
                )
            )
        )
    }
}
