package com.gabstra.myworkoutassistant.e2e.helpers

import androidx.activity.ComponentActivity
import androidx.lifecycle.ViewModelProvider
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import java.util.UUID

class CrossDeviceWorkoutFlowHelper(
    private val device: UiDevice,
    private val workoutDriver: WearWorkoutDriver
) {
    fun completeComplexWorkoutWithDeterministicModifications() {
        val modifiedSetIds = mutableSetOf<UUID>()
        val targetModifiedSetIds = setOf(
            CrossDeviceSyncWorkoutStoreFixture.SET_A1_ID,
            CrossDeviceSyncWorkoutStoreFixture.SET_D1_ID
        )
        val deadline = System.currentTimeMillis() + 180_000

        while (System.currentTimeMillis() < deadline) {
            if (isCompletionVisible()) {
                runCatching {
                    workoutDriver.confirmLongPressDialog(timeoutMs = 3_000)
                }
                break
            }

            if (isRestScreenVisible()) {
                val skipped = runCatching {
                    workoutDriver.skipRest(timeoutMs = 4_000)
                    true
                }.getOrElse { false }
                if (!skipped) {
                    waitForRestAutoAdvance(timeoutMs = 35_000)
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
                workoutDriver.completeCurrentSet(timeoutMs = 5_000)
                continue
            }

            device.waitForIdle(500)
        }

        require(isCompletionVisible()) {
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
        val deadline = System.currentTimeMillis() + 180_000

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
                    waitForRestAutoAdvance(timeoutMs = 35_000)
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

            device.waitForIdle(500)
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
            Until.hasObject(By.textContains("Select load for")),
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
            device.waitForIdle(500)
        }
        error("Rest screen did not auto-advance within ${timeoutMs}ms.")
    }

    private fun modifyRepsByPlusOne(): Boolean {
        val repsTarget = device.wait(
            Until.findObject(By.descContains(SetValueSemantics.RepsValueDescription)),
            5_000
        ) ?: return false

        val before = parseIntFromValueTarget(repsTarget) ?: return false
        repsTarget.longClick()
        device.waitForIdle(400)

        val addButton = device.wait(Until.findObject(By.desc("Add")), 2_000) ?: return false
        addButton.click()
        device.waitForIdle(300)

        device.wait(Until.findObject(By.desc("Close")), 1_500)?.click()
        device.waitForIdle(700)

        val afterTarget = device.wait(
            Until.findObject(By.descContains(SetValueSemantics.RepsValueDescription)),
            2_000
        ) ?: return false
        val after = parseIntFromValueTarget(afterTarget) ?: return false
        return after == before + 1
    }

    private fun parseIntFromValueTarget(target: UiObject2): Int? {
        val textValue = target.text?.trim()?.toIntOrNull()
        if (textValue != null) return textValue
        val desc = target.contentDescription?.toString() ?: return null
        val match = Regex("""(\d+)""").find(desc) ?: return null
        return match.value.toIntOrNull()
    }

    private fun getCurrentSetIdFromViewModel(): UUID? {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var setId: UUID? = null
        instrumentation.runOnMainSync {
            val activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull() as? ComponentActivity
                ?: return@runOnMainSync

            val viewModel = ViewModelProvider(activity)[AppViewModel::class.java]
            val currentState = viewModel.workoutState.value as? WorkoutState.Set ?: return@runOnMainSync
            setId = currentState.set.id
        }
        return setId
    }
}
