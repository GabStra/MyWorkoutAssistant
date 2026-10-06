package com.gabstra.myworkoutassistant

import androidx.compose.runtime.mutableStateOf
import com.gabstra.myworkoutassistant.data.WearActiveSessionSyncState
import com.gabstra.myworkoutassistant.data.resolveWearActiveSessionSyncState
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.initializeSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.UUID

class WearActiveSessionSyncStateTest {

    @Test
    fun `rest between exercises falls back to existing record coordinates`() {
        val recordExerciseId = UUID.randomUUID()
        val restState = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 60),
            order = 4u,
            currentSetDataState = mutableStateOf(initializeSetData(RestSet(UUID.randomUUID(), 60))),
            exerciseId = null
        )
        val existingRecord = WorkoutRecord(
            id = UUID.randomUUID(),
            workoutId = UUID.randomUUID(),
            workoutHistoryId = UUID.randomUUID(),
            setIndex = 2u,
            exerciseId = recordExerciseId,
            ownerDevice = "WEAR"
        )

        val resolved = resolveWearActiveSessionSyncState(restState, existingRecord)

        assertEquals(
            WearActiveSessionSyncState(
                exerciseId = recordExerciseId,
                setIndex = 2u,
                sessionState = "Rest"
            ),
            resolved
        )
    }

    @Test
    fun `set state uses its own exercise and index`() {
        val exerciseId = UUID.randomUUID()
        val setState = WorkoutState.Set(
            exerciseId = exerciseId,
            set = WeightSet(UUID.randomUUID(), 8, 80.0),
            setIndex = 3u,
            previousSetData = null,
            currentSetDataState = mutableStateOf(WeightSetData(actualReps = 8, actualWeight = 80.0, volume = 640.0)),
            hasNoHistory = false,
            skipped = false,
            equipmentId = null,
            currentBodyWeight = 0.0,
            streak = 0,
            progressionState = null,
            isWarmupSet = false
        )

        val resolved = resolveWearActiveSessionSyncState(setState, existingRecord = null)

        assertEquals(
            WearActiveSessionSyncState(
                exerciseId = exerciseId,
                setIndex = 3u,
                sessionState = "Set"
            ),
            resolved
        )
    }

    @Test
    fun `rest without existing record cannot resolve sync state`() {
        val restState = WorkoutState.Rest(
            set = RestSet(UUID.randomUUID(), 45),
            order = 1u,
            currentSetDataState = mutableStateOf(initializeSetData(RestSet(UUID.randomUUID(), 45))),
            exerciseId = null
        )

        val resolved = resolveWearActiveSessionSyncState(restState, existingRecord = null)

        assertNull(resolved)
    }
}
