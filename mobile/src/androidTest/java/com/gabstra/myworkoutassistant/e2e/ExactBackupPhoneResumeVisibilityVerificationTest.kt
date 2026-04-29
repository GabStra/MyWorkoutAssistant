package com.gabstra.myworkoutassistant.e2e

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.PhoneAppDriver
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class ExactBackupPhoneResumeVisibilityVerificationTest {

    @Test
    fun restoreExactBackup_thenTargetWorkoutShowsResumeOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = AppDatabase.getDatabase(context)
        restoreBackupThroughDialog(context)
        waitForTargetResumeRecordOnPhone(db)
        val targetWorkout = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
            .workouts
            .firstOrNull { it.id == TARGET_WORKOUT_ID }
            ?: error("Target workout $TARGET_WORKOUT_ID missing from restored workout store.")
        val targetPlanName = WorkoutStoreRepository(context.filesDir).getWorkoutStore()
            .workoutPlans
            .firstOrNull { it.id == targetWorkout.workoutPlanId }
            ?.name
            ?: error("Could not resolve workout plan for target workout ${targetWorkout.name}.")

        assertTargetResumeActionVisibleOnPhoneOverview(
            context = context,
            targetPlanName = targetPlanName,
            targetWorkoutName = targetWorkout.name
        )
    }

    private suspend fun waitForTargetResumeRecordOnPhone(db: AppDatabase) {
        val workoutRecordDao = db.workoutRecordDao()
        val workoutHistoryDao = db.workoutHistoryDao()
        val deadline = System.currentTimeMillis() + 30_000
        while (System.currentTimeMillis() < deadline) {
            val targetRecord = workoutRecordDao.getWorkoutRecordByWorkoutId(TARGET_WORKOUT_ID)
            if (targetRecord != null) {
                require(targetRecord.workoutHistoryId == TARGET_WORKOUT_HISTORY_ID) {
                    "Phone target record points to ${targetRecord.workoutHistoryId}, expected $TARGET_WORKOUT_HISTORY_ID"
                }
                val targetHistory = workoutHistoryDao.getWorkoutHistoryById(targetRecord.workoutHistoryId)
                requireNotNull(targetHistory) {
                    "Phone target workout history ${targetRecord.workoutHistoryId} missing after restore."
                }
                require(!targetHistory.isDone) {
                    "Phone target workout history ${targetHistory.id} is done; expected unfinished for resume."
                }
                return
            }
            delay(500)
        }
        error("Phone restore did not produce workout record for target workout $TARGET_WORKOUT_ID")
    }

    private fun assertTargetResumeActionVisibleOnPhoneOverview(
        context: Context,
        targetPlanName: String,
        targetWorkoutName: String
    ) {
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val driver = PhoneAppDriver(device, context)

        repeat(2) { attempt ->
            driver.launchAppFromHome()
            driver.dismissStartupPermissionDialogs(timeoutMs = 12_000)
            if (driver.waitForAppForeground(timeoutMs = 5_000)) {
                return@repeat
            }
            if (attempt == 1) {
                error("Main app shell was not visible after launch.")
            }
        }
        ensureHomeShellVisible(context, device, driver)
        openWorkoutsTab(device)
        selectWorkoutPlan(device, targetPlanName)
        openWorkoutFromList(device, targetWorkoutName)
        openOverviewTab(device)

        val resumeAction = device.wait(Until.findObject(By.textContains("Resume")), 10_000)
        requireNotNull(resumeAction) {
            "Target workout detail did not show Resume action on phone."
        }
    }

    private fun restoreBackupThroughDialog(context: Context) {
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val driver = PhoneAppDriver(device, context)
        driver.launchAppFromHome()
        driver.dismissStartupPermissionDialogs(timeoutMs = 12_000)
        driver.restoreBackupThroughFilePicker(
            backupFileName = BACKUP_FILE_NAME,
            backupFileNamePrefix = BACKUP_FILE_PREFIX,
            appPackageForBackupPath = "com.gabstra.myworkoutassistant.debug"
        )
    }

    private fun openWorkoutsTab(device: UiDevice) {
        val deadline = System.currentTimeMillis() + 10_000
        while (System.currentTimeMillis() < deadline) {
            val workoutsTab = device.findObject(By.text("Workouts"))
                ?: device.findObject(By.textContains("Workouts"))
            if (workoutsTab != null) {
                workoutsTab.click()
                device.waitForIdle(600)
                return
            }
            device.waitForIdle(300)
        }
        error("Workouts tab was not visible.")
    }

    private fun ensureHomeShellVisible(context: Context, device: UiDevice, driver: PhoneAppDriver) {
        val deadline = System.currentTimeMillis() + 12_000
        while (System.currentTimeMillis() < deadline) {
            val inAppForeground = device.hasObject(By.pkg(context.packageName).depth(0))
            val hasMenu = device.findObject(By.desc("Menu")) != null
            if (inAppForeground && hasMenu) return

            if (!inAppForeground) {
                driver.launchAppFromHome()
                driver.dismissStartupPermissionDialogs(timeoutMs = 4_000)
            } else {
                device.pressBack()
                device.waitForIdle(300)
            }
            device.waitForIdle(300)
        }
        error("Could not reach app home shell with top menu visible.")
    }

    private fun selectWorkoutPlan(device: UiDevice, planName: String) {
        val picker = device.wait(Until.findObject(By.textContains("Workout Plan")), 8_000)
            ?: error("Workout Plan filter picker was not visible.")
        picker.click()
        device.waitForIdle(500)

        val planOption = device.wait(Until.findObject(By.text(planName)), 8_000)
            ?: error("Workout plan '$planName' was not visible in plan picker.")
        planOption.click()
        device.waitForIdle(700)
    }

    private fun openWorkoutFromList(device: UiDevice, workoutName: String) {
        val targetWorkout = findWorkoutInList(device = device, workoutName = workoutName, timeoutMs = 20_000)
            ?: error("Workout '$workoutName' was not visible in selected plan list.")
        targetWorkout.click()
        device.waitForIdle(1_000)
    }

    private fun openOverviewTab(device: UiDevice) {
        device.wait(Until.findObject(By.text("Overview")), 5_000)?.click()
        device.waitForIdle(500)
    }

    private fun findWorkoutInList(
        device: UiDevice,
        workoutName: String,
        timeoutMs: Long
    ): androidx.test.uiautomator.UiObject2? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val byStableCardDesc = device.findObject(By.desc("Open workout: $workoutName"))
                ?: device.findObject(By.descContains("Open workout: $workoutName"))
                ?: device.findObject(By.descContains(workoutName))
            if (byStableCardDesc != null) return byStableCardDesc

            val workout = device.findObject(By.text(workoutName))
                ?: device.findObject(By.textContains(workoutName))
            if (workout != null) return workout

            val scrollable = device.findObject(By.scrollable(true))
            if (scrollable != null) {
                runCatching { scrollable.scroll(Direction.DOWN, 0.8f) }
            } else {
                val x = device.displayWidth / 2
                val yStart = (device.displayHeight * 0.8).toInt()
                val yEnd = (device.displayHeight * 0.25).toInt()
                device.swipe(x, yStart, x, yEnd, 15)
            }
            device.waitForIdle(300)
        }
        return null
    }

    companion object {
        private const val BACKUP_FILE_NAME = "workout_store_backup_2026-04-28_18-12-49.json"
        private const val BACKUP_FILE_PREFIX = "workout_store_backup_2026-04-28"
        private val TARGET_WORKOUT_ID = UUID.fromString("efdba35b-82bf-418e-9362-4ffa2d39e435")
        private val TARGET_WORKOUT_HISTORY_ID = UUID.fromString("9b67898a-febe-4c09-9d4e-830cff9ca864")
    }
}
