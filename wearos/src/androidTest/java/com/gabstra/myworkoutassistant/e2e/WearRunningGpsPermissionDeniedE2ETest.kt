package com.gabstra.myworkoutassistant.e2e

import android.Manifest
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.Until
import androidx.test.uiautomator.BySelector
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.services.RunningTrackingService
import com.gabstra.myworkoutassistant.shared.AppDatabase
import java.io.File
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import java.util.regex.Pattern
import org.junit.After
import org.junit.Before
import org.junit.Test

class WearRunningGpsPermissionDeniedE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
    }

    override fun runtimePermissionsToGrant(): List<String> = super.runtimePermissionsToGrant()
        .filterNot { it == Manifest.permission.ACCESS_FINE_LOCATION || it == Manifest.permission.ACCESS_COARSE_LOCATION }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @After
    override fun baseTearDown() {
        runCatching { RunningTrackingService.stop(context) }
        runCatching { grantPermissions(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION) }
        super.baseTearDown()
    }

    @Test
    fun denyingOutdoorLocation_keepsTimerAndCompletesWithoutRoute() = runBlocking {
        startWorkout(RUNNING_PLAN_NAME)
        navigateToRunControls()
        require(context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            "Starting the workout should not grant location before the outdoor running step requests it."
        }
        clickText("Start run")

        val denialSelector: BySelector = By.text(Pattern.compile("(?i).*(don.?t allow|deny).*"))
        var denyButton = device.wait(Until.findObject(denialSelector), 2_000)
        repeat(4) {
            if (denyButton == null) {
                val permissionDialog = device.findObject(By.scrollable(true))
                if (permissionDialog != null) {
                    runCatching { permissionDialog.scroll(Direction.DOWN, 0.8f) }
                } else {
                    device.swipe(device.displayWidth / 2, device.displayHeight * 9 / 10, device.displayWidth / 2, device.displayHeight / 3, 15)
                }
                device.waitForIdle(250)
                denyButton = device.wait(Until.findObject(denialSelector), 1_000)
            }
        }
        val deniedAction = denyButton
            ?: device.findObjects(By.clickable(true)).firstOrNull { button ->
                button.text?.contains("don't", ignoreCase = true) == true ||
                    button.text?.contains("deny", ignoreCase = true) == true
            }
            ?: run {
                val hierarchy = File(context.cacheDir, "running_permission_denial_missing.xml")
                device.dumpWindowHierarchy(hierarchy)
                device.takeScreenshot(File(context.cacheDir, "running_permission_denial_missing.png"))
                val visibleText = device.findObjects(By.text(Pattern.compile(".+"))).joinToString { it.text }
                error("The first outdoor run request did not show a recognizable denial action. Visible text=$visibleText, hierarchy=${hierarchy.absolutePath}")
            }
        workoutDriver.clickObjectOrAncestor(deniedAction)
        device.waitForIdle()

        require(device.wait(Until.hasObject(By.text("OUTDOOR RUN")), 5_000)) {
            "Denying location permission should leave the workout on its outdoor run step."
        }
        waitForTrackingState(timeoutMs = 10_000) { it.running }
        require(device.wait(Until.hasObject(By.desc("GPS unavailable; no route saved")), 5_000)) {
            "The outdoor screen must explain that GPS and its route are unavailable after permission denial."
        }
        delay(2_000)
        require(RunningTrackingService.state.value.running) {
            "Denying location permission should still allow elapsed-time tracking."
        }

        workoutDriver.openRunningControls()
        clickLabel("Finish run")
        require(device.wait(Until.hasObject(By.text("TREADMILL RUN")), 15_000)) {
            "Manual finish after permission denial did not advance to the next planned step."
        }
        navigateToRunControls()
        clickText("Start run")
        delay(1_000)
        workoutDriver.openRunningControls()
        clickLabel("Finish run")
        require(device.wait(Until.hasObject(By.descContains("Edit treadmill distance")), 5_000)) {
            "Treadmill distance edit affordance was not shown after the outdoor run."
        }
        clickDescriptionContaining("Edit treadmill distance")
        require(device.wait(Until.hasObject(By.text(Pattern.compile("DISTANCE \\((km|mi)\\)"))), 5_000)) {
            "Treadmill distance adjustment controls did not open."
        }
        clickLabel("Add")
        clickLabel("Back")
        clickText("Save run")
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 20_000)

        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + 30_000
        var history: com.gabstra.myworkoutassistant.shared.WorkoutHistory? = null
        while (System.currentTimeMillis() < deadline) {
            history = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
                .singleOrNull { it.workoutId.toString() == RUNNING_WORKOUT_ID }
            if (history?.runningResults?.size == 2) break
            delay(250)
        }
        val saved = requireNotNull(history) { "Completed running history was not persisted after permission denial." }
        val outdoor = saved.runningResults.single { it.exerciseId == OUTDOOR_EXERCISE_ID }
        val treadmill = saved.runningResults.single { it.exerciseId == TREADMILL_EXERCISE_ID }
        require(outdoor.elapsedTimeMillis > 0) { "Outdoor elapsed time was not saved after permission denial." }
        require(outdoor.route.isEmpty()) { "Denied location permission must not save route points." }
        require((treadmill.distanceMeters ?: 0.0) > 0.0) { "Treadmill correction was not saved." }

        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }

    private fun navigateToRunControls() {
        repeat(5) {
            if (device.wait(Until.hasObject(By.desc("Start run")), 1_000) ||
                device.wait(Until.hasObject(By.text("Start run")), 250)
            ) return
            workoutDriver.navigateToPagerPage(Direction.LEFT)
        }
        val hierarchy = File(context.cacheDir, "running_permission_controls_missing.xml")
        device.dumpWindowHierarchy(hierarchy)
        val visibleText = device.findObjects(By.text(Pattern.compile(".+"))).joinToString { it.text }
        error("Could not navigate to the planned running controls. Visible text=$visibleText, hierarchy=${hierarchy.absolutePath}")
    }

    private fun clickText(text: String) {
        val textSelector = By.text(text)
        val target = device.wait(Until.findObject(textSelector), 15_000)
            ?: (if (text == "Start run") device.wait(Until.findObject(By.desc(text)), 1_000) else null)
            ?: error("Timed out waiting for '$text' on the running step.")
        workoutDriver.clickObjectOrAncestor(target)
        device.waitForIdle()
    }

    private fun clickLabel(label: String) {
        val target = device.wait(Until.findObject(By.desc(label)), 15_000)
            ?: run {
                val hierarchy = File(context.cacheDir, "running_permission_label_missing.xml")
                device.dumpWindowHierarchy(hierarchy)
                device.takeScreenshot(File(context.cacheDir, "running_permission_label_missing.png"))
                val clickableNodes = device.findObjects(By.clickable(true)).joinToString {
                    "text=${it.text}, desc=${it.contentDescription}, bounds=${it.visibleBounds}"
                }
                error("Timed out waiting for '$label' on the running step. Clickable nodes=$clickableNodes, hierarchy=${hierarchy.absolutePath}")
            }
        workoutDriver.clickObjectOrAncestor(target)
        device.waitForIdle()
    }

    private fun clickDescriptionContaining(description: String) {
        val target = device.wait(Until.findObject(By.descContains(description)), 5_000)
            ?: error("Timed out waiting for accessibility description containing '$description'.")
        workoutDriver.clickObjectOrAncestor(target)
        device.waitForIdle()
    }

    private suspend fun waitForTrackingState(timeoutMs: Long, predicate: (com.gabstra.myworkoutassistant.services.RunningTrackingState) -> Boolean) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (predicate(RunningTrackingService.state.value)) return
            delay(250)
        }
        error("Timed out waiting for tracking state: ${RunningTrackingService.state.value}")
    }

    companion object {
        private const val RUNNING_PLAN_NAME = "Cross Device Running Plan"
        private const val RUNNING_WORKOUT_ID = "65d1f21a-459c-4376-8a99-2fa1328f4f50"
        private const val OUTDOOR_EXERCISE_ID = "75398883-7cf8-42b3-8c44-0e8e394480f0"
        private const val TREADMILL_EXERCISE_ID = "5cba1938-3093-40fa-934e-5c63fd6af852"
    }
}
