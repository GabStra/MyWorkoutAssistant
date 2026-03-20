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

    fun completeCurrentSet(device: UiDevice, context: Context, timeoutMs: Long = 15_000): Boolean {
        val currentSetId = getCurrentSetId() ?: return false
        var invoked = false

        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@withResumedViewModel
            viewModel.storeSetData()
            val isDone = viewModel.isNextStateCompleted()
            viewModel.pushAndStoreWorkoutData(
                isDone = isDone,
                context = context.applicationContext,
                forceNotSend = false
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

    fun skipCurrentRest(device: UiDevice, timeoutMs: Long = 5_000): Boolean {
        val currentRestId = when (val snapshot = readCurrentStateSnapshot()) {
            is CurrentStateSnapshot.RestState -> snapshot.setId
            else -> return false
        }
        var invoked = false

        withResumedViewModel { viewModel ->
            val currentState = viewModel.workoutState.value as? WorkoutState.Rest ?: return@withResumedViewModel
            viewModel.goToNextState()
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

    private fun withResumedViewModel(block: (AppViewModel) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? ComponentActivity
                ?: return@runOnMainSync
            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]
            block(viewModel)
        }
    }

    private fun readCurrentStateSnapshot(): CurrentStateSnapshot {
        var snapshot: CurrentStateSnapshot = CurrentStateSnapshot.Unavailable
        withResumedViewModel { viewModel ->
            snapshot = when (val currentState = viewModel.workoutState.value) {
                is WorkoutState.Set -> CurrentStateSnapshot.SetState(currentState.set.id)
                is WorkoutState.Rest -> CurrentStateSnapshot.RestState(currentState.set.id)
                else -> CurrentStateSnapshot.Advanced
            }
        }
        return snapshot
    }

    private sealed interface CurrentStateSnapshot {
        data class SetState(val setId: UUID) : CurrentStateSnapshot
        data class RestState(val setId: UUID) : CurrentStateSnapshot
        data object Advanced : CurrentStateSnapshot
        data object Unavailable : CurrentStateSnapshot
    }
}
