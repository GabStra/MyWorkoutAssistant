package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import androidx.activity.ComponentActivity
import androidx.lifecycle.ViewModelProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.uiautomator.UiDevice
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import java.util.UUID

object WearWorkoutStateMutationHelper {
    data class WeightSetComparisonSnapshot(
        val previousSetData: WeightSetData?,
        val currentSetData: WeightSetData?
    )

    fun addRestAfterCurrent(device: UiDevice, context: Context, timeoutMs: Long = 10_000): Boolean {
        return mutateCurrentSetStructure(
            device = device,
            context = context,
            timeoutMs = timeoutMs
        ) { viewModel ->
            viewModel.addNewRest()
        }
    }

    fun addSetAfterCurrent(device: UiDevice, context: Context, timeoutMs: Long = 10_000): Boolean {
        return mutateCurrentSetStructure(
            device = device,
            context = context,
            timeoutMs = timeoutMs
        ) { viewModel ->
            viewModel.addNewSetStandard()
        }
    }

    fun addRestPauseSetAfterCurrent(device: UiDevice, context: Context, timeoutMs: Long = 10_000): Boolean {
        return mutateCurrentSetStructure(
            device = device,
            context = context,
            timeoutMs = timeoutMs
        ) { viewModel ->
            viewModel.addNewRestPauseSet()
        }
    }

    fun incrementCurrentSetRepsByOne(device: UiDevice): Boolean {
        var updated = false
        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            currentState.currentSetData = when (val setData = currentState.currentSetData) {
                is WeightSetData -> {
                    val nextData = setData.copy(actualReps = setData.actualReps + 1)
                    nextData.copy(volume = nextData.calculateVolume())
                }
                is BodyWeightSetData -> {
                    val nextData = setData.copy(actualReps = setData.actualReps + 1)
                    nextData.copy(volume = nextData.calculateVolume())
                }
                else -> return@withResumedViewModel
            }
            updated = true
        }

        if (updated) {
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }
        return updated
    }

    fun updateCurrentWeightSet(
        device: UiDevice,
        actualReps: Int? = null,
        actualWeight: Double? = null
    ): Boolean {
        var updated = false
        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            currentState.currentSetData = when (val setData = currentState.currentSetData) {
                is WeightSetData -> {
                    val nextData = setData.copy(
                        actualReps = actualReps ?: setData.actualReps,
                        actualWeight = actualWeight ?: setData.actualWeight
                    )
                    nextData.copy(volume = nextData.calculateVolume())
                }
                else -> return@withResumedViewModel
            }
            updated = true
        }

        if (updated) {
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }
        return updated
    }

    fun completeCurrentSet(
        device: UiDevice,
        context: Context,
        timeoutMs: Long = 15_000,
        forceNotSend: Boolean = false
    ): Boolean {
        val currentSetId = getCurrentSetId() ?: return false
        var invoked = false

        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            viewModel.storeSetData()
            val isDone = viewModel.isNextStateCompleted()
            viewModel.pushAndStoreWorkoutData(
                isDone = isDone,
                context = context.applicationContext,
                forceNotSend = forceNotSend
            ) {
                viewModel.goToNextState()
            }
            invoked = true
        }

        if (!invoked) {
            return false
        }

        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            when (val snapshot = readCurrentStateSnapshot()) {
                CurrentStateSnapshot.Advanced -> {
                    device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                    return true
                }
                is CurrentStateSnapshot.SetState -> {
                    if (snapshot.setId != currentSetId) {
                        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                        return true
                    }
                }
                is CurrentStateSnapshot.RestState -> {
                    device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                    return true
                }
                CurrentStateSnapshot.Unavailable -> Unit
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        return false
    }

    fun completeCurrentAutoRegulationSet(device: UiDevice, timeoutMs: Long = 15_000): Boolean {
        val currentSetId = getCurrentSetId() ?: return false
        var invoked = false

        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            if (!currentState.isAutoRegulationWorkSet) return@withResumedViewModel
            viewModel.storeSetData()
            viewModel.completeAutoRegulationSet()
            invoked = true
        }

        if (!invoked) {
            return false
        }

        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            when (val snapshot = readCurrentStateSnapshot()) {
                CurrentStateSnapshot.Advanced -> {
                    device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                    return true
                }
                is CurrentStateSnapshot.SetState -> {
                    if (snapshot.setId != currentSetId) {
                        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                        return true
                    }
                }
                is CurrentStateSnapshot.RestState -> {
                    device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                    return true
                }
                CurrentStateSnapshot.Unavailable -> Unit
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        return false
    }

    fun skipCurrentRest(
        device: UiDevice,
        timeoutMs: Long = 5_000,
        forceNotSend: Boolean = false
    ): Boolean {
        val currentRestId = when (val snapshot = readCurrentStateSnapshot()) {
            is CurrentStateSnapshot.RestState -> snapshot.setId
            else -> return false
        }
        var invoked = false
        val appContext = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext

        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Rest ?: return@withResumedViewModel
            viewModel.storeSetData()
            val isDone = viewModel.isNextStateCompleted()
            viewModel.pushAndStoreWorkoutData(
                isDone = isDone,
                context = appContext,
                forceNotSend = forceNotSend
            ) {
                viewModel.goToNextState()
            }
            invoked = true
        }

        if (!invoked) {
            return false
        }

        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            when (val snapshot = readCurrentStateSnapshot()) {
                CurrentStateSnapshot.Advanced -> {
                    device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                    return true
                }
                is CurrentStateSnapshot.SetState -> {
                    device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                    return true
                }
                is CurrentStateSnapshot.RestState -> {
                    if (snapshot.setId != currentRestId) {
                        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                        return true
                    }
                }
                CurrentStateSnapshot.Unavailable -> Unit
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        return false
    }

    fun getCurrentSetId(): UUID? {
        return when (val snapshot = readCurrentStateSnapshot()) {
            is CurrentStateSnapshot.SetState -> snapshot.setId
            is CurrentStateSnapshot.RestState,
            CurrentStateSnapshot.Advanced,
            CurrentStateSnapshot.Unavailable -> null
        }
    }

    fun getCurrentExerciseId(): UUID? {
        return when (val snapshot = readCurrentStateSnapshot()) {
            is CurrentStateSnapshot.SetState -> snapshot.exerciseId
            is CurrentStateSnapshot.RestState -> snapshot.exerciseId
            CurrentStateSnapshot.Advanced,
            CurrentStateSnapshot.Unavailable -> null
        }
    }

    fun getHistoricalWeightSetData(exerciseId: UUID, setId: UUID): WeightSetData? {
        var historicalSetData: WeightSetData? = null
        withResumedViewModel { viewModel ->
            historicalSetData = viewModel.getAllSetHistoriesByExerciseId(exerciseId)
                .firstOrNull { it.setId == setId }
                ?.setData as? WeightSetData
        }
        return historicalSetData
    }

    fun getHistoricalSetIds(exerciseId: UUID): List<UUID> {
        var setIds: List<UUID> = emptyList()
        withResumedViewModel { viewModel ->
            setIds = viewModel.getAllSetHistoriesByExerciseId(exerciseId).map { it.setId }
        }
        return setIds
    }

    fun getCurrentWeightSetData(): WeightSetData? {
        var currentSetData: WeightSetData? = null
        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            currentSetData = currentState.currentSetData as? WeightSetData
        }
        return currentSetData
    }

    fun getCurrentWeightSetComparisonSnapshot(): WeightSetComparisonSnapshot? {
        var snapshot: WeightSetComparisonSnapshot? = null
        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            snapshot = WeightSetComparisonSnapshot(
                previousSetData = currentState.previousSetData as? WeightSetData,
                currentSetData = currentState.currentSetData as? WeightSetData
            )
        }
        return snapshot
    }

    fun isWorkoutCompleted(): Boolean {
        var completed = false
        withResumedViewModel { viewModel ->
            completed = viewModel.workoutState.value is WorkoutState.Completed
        }
        return completed
    }

    fun describeCurrentState(): String {
        return when (val snapshot = readCurrentStateSnapshot()) {
            is CurrentStateSnapshot.SetState -> "set:${snapshot.setId}"
            is CurrentStateSnapshot.RestState -> "rest:${snapshot.setId}"
            CurrentStateSnapshot.Advanced -> "advanced"
            CurrentStateSnapshot.Unavailable -> "unavailable"
        }
    }

    private fun mutateCurrentSetStructure(
        device: UiDevice,
        context: Context,
        timeoutMs: Long,
        mutation: (AppViewModel) -> Unit
    ): Boolean {
        val currentSetId = getCurrentSetId() ?: return false
        var invoked = false

        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            viewModel.storeSetData()
            viewModel.pushAndStoreWorkoutData(
                isDone = false,
                context = context.applicationContext,
                forceNotSend = false
            ) {
                mutation(viewModel)
            }
            invoked = true
        }

        if (!invoked) {
            return false
        }

        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            when (val snapshot = readCurrentStateSnapshot()) {
                is CurrentStateSnapshot.RestState -> {
                    device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                    return true
                }
                is CurrentStateSnapshot.SetState -> {
                    if (snapshot.setId != currentSetId) {
                        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                        return true
                    }
                }
                CurrentStateSnapshot.Advanced,
                CurrentStateSnapshot.Unavailable -> Unit
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        return false
    }

    private fun withResumedViewModel(block: (AppViewModel) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val monitor = ActivityLifecycleMonitorRegistry.getInstance()
            val activity = (
                monitor.getActivitiesInStage(Stage.RESUMED).firstOrNull()
                    ?: monitor.getActivitiesInStage(Stage.STARTED).firstOrNull()
                ) as? ComponentActivity
                ?: return@runOnMainSync
            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]
            block(viewModel)
        }
    }

    private fun readCurrentStateSnapshot(): CurrentStateSnapshot {
        var snapshot: CurrentStateSnapshot = CurrentStateSnapshot.Unavailable
        withResumedViewModel { viewModel ->
            snapshot = when (val currentState = viewModel.workoutState.value) {
                is WorkoutState.Set -> CurrentStateSnapshot.SetState(
                    setId = currentState.set.id,
                    exerciseId = currentState.exerciseId
                )
                is WorkoutState.Rest -> CurrentStateSnapshot.RestState(
                    setId = currentState.set.id,
                    exerciseId = currentState.exerciseId ?: extractExerciseIdFromNextState(currentState.nextState)
                )
                else -> CurrentStateSnapshot.Advanced
            }
        }
        return snapshot
    }

    private fun extractExerciseIdFromNextState(nextState: WorkoutState?): UUID? =
        when (nextState) {
            is WorkoutState.Set -> nextState.exerciseId
            is WorkoutState.CalibrationLoadSelection -> nextState.exerciseId
            is WorkoutState.CalibrationRIRSelection -> nextState.exerciseId
            is WorkoutState.AutoRegulationRIRSelection -> nextState.exerciseId
            else -> null
        }

    private sealed interface CurrentStateSnapshot {
        data class SetState(val setId: UUID, val exerciseId: UUID) : CurrentStateSnapshot
        data class RestState(val setId: UUID, val exerciseId: UUID?) : CurrentStateSnapshot
        data object Advanced : CurrentStateSnapshot
        data object Unavailable : CurrentStateSnapshot
    }
}
