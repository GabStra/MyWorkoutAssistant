package com.gabstra.myworkoutassistant.e2e.helpers

import android.os.SystemClock
import androidx.activity.ComponentActivity
import androidx.lifecycle.ViewModelProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import java.util.UUID

class CrossDeviceWorkoutFlowHelper(
    private val device: UiDevice,
    private val workoutDriver: WearWorkoutDriver
) {
    fun waitForIntermediateSyncObservationWindow(
        durationMs: Long = E2ETestTimings.CROSS_DEVICE_INTERMEDIATE_SYNC_SETTLE_MS
    ) {
        device.waitForIdle(E2ETestTimings.LONG_IDLE_MS)
        SystemClock.sleep(durationMs)
        device.waitForIdle(E2ETestTimings.LONG_IDLE_MS)
    }

    fun completeComplexWorkoutWithDeterministicModifications(
        timeoutMs: Long = E2ETestTimings.CROSS_DEVICE_WORKOUT_TIMEOUT_MS,
        perSettleMs: Long = E2ETestTimings.CROSS_DEVICE_INTERMEDIATE_SYNC_SETTLE_MS
    ) {
        val modifiedSetIds = mutableSetOf<UUID>()
        val targetModifiedSetIds = setOf(
            CrossDeviceSyncWorkoutStoreFixture.SET_A1_ID,
            CrossDeviceSyncWorkoutStoreFixture.SET_D1_ID
        )
        val deadline = System.currentTimeMillis() + timeoutMs

        while (System.currentTimeMillis() < deadline) {
            if (isCompletionVisible() || isCompletionStateFromViewModel()) {
                runCatching {
                    workoutDriver.confirmLongPressDialog(timeoutMs = 3_000)
                }
                break
            }

            if (isRestScreenVisible()) {
                val skipped = WearWorkoutStateMutationHelper.skipCurrentRest(
                    device = device,
                    timeoutMs = 5_000
                ) || runCatching {
                    workoutDriver.skipRest(timeoutMs = 4_000)
                    true
                }.getOrElse { false }
                if (!skipped) {
                    waitForRestAutoAdvance(timeoutMs = E2ETestTimings.CROSS_DEVICE_REST_AUTO_ADVANCE_TIMEOUT_MS)
                }
                continue
            }

            if (isCalibrationRirScreenVisible()) {
                runCatching {
                    workoutDriver.selectRIRAndConfirm(targetRir = 2, timeoutMs = 8_000)
                }
                continue
            }

            if (isCalibrationLoadScreenVisible()) {
                device.pressBack()
                runCatching {
                    workoutDriver.confirmLongPressDialog(timeoutMs = 5_000)
                }
                continue
            }

            if (isWeightSetScreenVisible()) {
                val currentSetId = getCurrentSetIdFromViewModel()
                if (currentSetId != null &&
                    currentSetId in targetModifiedSetIds &&
                    currentSetId !in modifiedSetIds
                ) {
                    val modified = modifyRepsByPlusOne()
                    require(modified) { "Failed to modify reps for target set $currentSetId" }
                    modifiedSetIds.add(currentSetId)
                }
                val completed = WearWorkoutStateMutationHelper.completeCurrentSet(
                    device = device,
                    context = InstrumentationRegistry.getInstrumentation().targetContext,
                    timeoutMs = 20_000
                )
                require(completed) { "Failed to advance past set $currentSetId" }
                if (waitForCompletionState(timeoutMs = 8_000)) {
                    break
                }
                waitForIntermediateSyncObservationWindow(durationMs = perSettleMs)
                continue
            }

            // If a confirmation dialog is already visible, clear it so progression can continue.
            if (device.wait(Until.hasObject(By.desc("Done")), 500)) {
                runCatching {
                    workoutDriver.confirmLongPressDialog(timeoutMs = 3_000)
                }
                continue
            }

            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        require(isCompletionVisible() || isCompletionStateFromViewModel()) {
            "Workout did not reach completion screen within timeout."
        }
        require(modifiedSetIds == targetModifiedSetIds) {
            "Not all targeted sets were modified. expected=$targetModifiedSetIds actual=$modifiedSetIds"
        }
    }

    fun completeCalibrationWorkoutFlow(
        workoutName: String,
        resumeWorkoutIfPaused: (String) -> Unit
    ) {
        var sawCalibrationLoad = false
        var sawCalibrationRir = false
        var progressedAfterCalibrationRir = false
        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_WORKOUT_TIMEOUT_MS

        while (System.currentTimeMillis() < deadline) {
            if (isCompletionVisible()) {
                break
            }

            if (isCalibrationLoadScreenVisible()) {
                sawCalibrationLoad = true
                device.pressBack()
                workoutDriver.confirmLongPressDialog(timeoutMs = 5_000)
                continue
            }

            if (isCalibrationRirScreenVisible()) {
                sawCalibrationRir = true
                device.pressBack()
                workoutDriver.confirmLongPressDialog(timeoutMs = 5_000)
                progressedAfterCalibrationRir = device.wait(
                    Until.gone(By.text("0 = Form Breaks")),
                    5_000
                )
                continue
            }

            if (isRestScreenVisible()) {
                val skipped = runCatching {
                    workoutDriver.skipRest(timeoutMs = 4_000)
                    true
                }.getOrElse { false }
                if (!skipped) {
                    waitForRestAutoAdvance(timeoutMs = E2ETestTimings.CROSS_DEVICE_REST_AUTO_ADVANCE_TIMEOUT_MS)
                }
                continue
            }

            if (isWeightSetScreenVisible() || isCalibrationExerciseVisible()) {
                workoutDriver.completeCurrentSet(timeoutMs = 5_000)
                continue
            }

            if (isWorkoutSelectionVisible()) {
                resumeWorkoutIfPaused(workoutName)
                continue
            }

            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        require(sawCalibrationLoad) {
            "Calibration workout flow did not show calibration load selection."
        }
        require(sawCalibrationRir) {
            "Calibration workout flow did not show calibration RIR selection."
        }
        require(progressedAfterCalibrationRir) {
            "Calibration workout flow did not progress after confirming calibration RIR."
        }
    }

    private fun isWeightSetScreenVisible(): Boolean {
        return device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
            1_000
        ) || device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.BodyWeightSetTypeDescription)),
            1_000
        )
    }

    private fun isRestScreenVisible(): Boolean {
        return device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription)),
            1_000
        )
    }

    private fun isCalibrationLoadScreenVisible(): Boolean {
        return device.wait(
            Until.hasObject(By.textContains("Set load for")),
            1_000
        )
    }

    private fun isCalibrationRirScreenVisible(): Boolean {
        return device.wait(
            Until.hasObject(By.text("0 = Form Breaks")),
            1_000
        )
    }

    private fun isCompletionVisible(): Boolean {
        return device.wait(Until.hasObject(By.text("Completed")), 500) ||
            device.wait(Until.hasObject(By.text("Workout completed")), 500)
    }

    private fun isCompletionStateFromViewModel(): Boolean {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var isCompleted = false
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? ComponentActivity
                ?: return@runOnMainSync
            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]
            isCompleted = viewModel.workoutState.value is WorkoutState.Completed
        }
        return isCompleted
    }

    private fun waitForCompletionState(timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (isCompletionVisible() || isCompletionStateFromViewModel()) {
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    private fun isWorkoutSelectionVisible(): Boolean {
        return device.wait(Until.hasObject(By.text("My Workout Assistant")), 500)
    }

    private fun isCalibrationExerciseVisible(): Boolean {
        return device.wait(
            Until.hasObject(By.text(CrossDeviceSyncWorkoutStoreFixture.CALIBRATION_EXERCISE_NAME)),
            500
        )
    }

    private fun waitForRestAutoAdvance(timeoutMs: Long) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (!isRestScreenVisible()) {
                return
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        error("Rest screen did not auto-advance within ${timeoutMs}ms.")
    }

    private fun modifyRepsByPlusOne(): Boolean {
        return WearWorkoutStateMutationHelper.incrementCurrentSetRepsByOne(device)
    }

    private fun getCurrentSetIdFromViewModel(): UUID? {
        return WearWorkoutStateMutationHelper.getCurrentSetId()
    }
}
