package com.gabstra.myworkoutassistant.e2e

import android.location.Criteria
import android.location.Location
import android.location.LocationManager
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.Until
import java.io.File
import java.io.FileInputStream
import java.util.regex.Pattern
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceWearSyncStateHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.services.RunningTrackingService
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearRunningGpsCrossDeviceProducerE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver
    private lateinit var locationManager: LocationManager
    private var testGpsProviderRegistered = false
    private var nextGpsFixIndex = 0

    override fun prepareAppStateBeforeLaunch() {
        CrossDeviceWearSyncStateHelper.clearWearHistoryState(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        setEmulatorLocationEnabled(true)
        locationManager = context.getSystemService(LocationManager::class.java)
        setMockLocationAppOp(allowed = true)
        addTestGpsProvider()
        workoutDriver = createWorkoutDriver()
    }

    @After
    override fun baseTearDown() {
        runCatching { setEmulatorLocationEnabled(true) }
        runCatching { RunningTrackingService.stop(context) }
        runCatching { removeTestGpsProvider() }
        runCatching { setMockLocationAppOp(allowed = false) }
        runCatching {
            grantPermissions(
                android.Manifest.permission.ACCESS_FINE_LOCATION,
                android.Manifest.permission.ACCESS_COARSE_LOCATION,
            )
        }
        super.baseTearDown()
    }

    @Test
    fun outdoorGpsAndTreadmillResults_syncWithCompletedWorkout() = runBlocking {
        startWorkout(RUNNING_PLAN_NAME)
        navigateToRunControls()
        waitForText("OUTDOOR RUN", 5_000)
        waitForTrackingState(timeoutMs = 10_000) { it.running }
        injectGpsLocations(count = 5)
        waitForTrackingState(timeoutMs = 15_000) { it.running && it.route.size >= 5 }
        waitForTrackingState(timeoutMs = 15_000) {
            it.running && it.distanceMeters?.let { distance -> distance > 0.0 } == true
        }
        require(RunningTrackingService.state.value.running) {
            "Tapping Start run did not start the tracking service. State: ${RunningTrackingService.state.value}"
        }

        val targetAlertAppeared = device.wait(Until.hasObject(By.desc("Goal reached")), 15_000)
        if (!targetAlertAppeared) {
            val hierarchy = File(context.cacheDir, "running_gps_target_missing.xml")
            device.dumpWindowHierarchy(hierarchy)
            val visibleText = device.findObjects(By.text(Pattern.compile(".+"))).joinToString { it.text }
            error(
                "Distance target was reached by the injected GPS route but no target alert appeared. " +
                    "Tracker=${RunningTrackingService.state.value}, visibleText=$visibleText, hierarchy=${hierarchy.absolutePath}"
            )
        }
        require(device.hasObject(By.text("OUTDOOR RUN"))) {
            "Reaching the run target should alert without advancing the workout."
        }

        require(RunningTrackingService.state.value.locationAvailable) {
            "Mock GPS fixes were not reported as available."
        }

        val routeBeforeActivityRecovery = RunningTrackingService.state.value.route.size
        device.pressHome()
        device.waitForIdle(1_000)
        launchAppFromHome()
        require(workoutDriver.waitForRecoveryDialog(15_000)) {
            "Reopening the app during an active GPS run did not show workout recovery."
        }
        val recoveryResult = workoutDriver.resumeOrEnterRecoveredWorkoutTimed(
            workoutName = RUNNING_PLAN_NAME,
            inWorkoutSelector = By.text("OUTDOOR RUN"),
            timeoutMs = 20_000,
        )
        require(recoveryResult.enteredWorkout) {
            "Could not resume the active GPS run from workout recovery. " +
                "Recovery=${workoutDriver.isRecoveryDialogVisible()}, route=${RunningTrackingService.state.value.route.size}"
        }
        waitForTrackingState(timeoutMs = 10_000) {
            it.running && it.route.size >= routeBeforeActivityRecovery
        }
        require(device.wait(Until.hasObject(By.text("OUTDOOR RUN")), 10_000)) {
            "Workout recovery did not return to the active outdoor running step."
        }

        workoutDriver.openRunningControls()
        clickLabel("Pause run")
        waitForTrackingState(timeoutMs = 5_000) { it.paused }
        val pausedRouteSize = RunningTrackingService.state.value.route.size
        val pausedElapsedTime = RunningTrackingService.state.value.elapsedTimeMillis
        val pausedDistanceMeters = RunningTrackingService.state.value.distanceMeters
        delay(2_500)
        require(RunningTrackingService.state.value.route.size == pausedRouteSize) {
            "GPS route continued to grow while the run was paused."
        }
        require(RunningTrackingService.state.value.elapsedTimeMillis == pausedElapsedTime) {
            "Run elapsed time continued to advance while paused."
        }
        require(RunningTrackingService.state.value.distanceMeters == pausedDistanceMeters) {
            "Health Services distance continued to advance while the run was paused."
        }
        workoutDriver.openRunningControls()
        clickLabel("Resume run")
        waitForTrackingState(timeoutMs = 5_000) { !it.paused }
        injectGpsLocations(count = 1)
        waitForTrackingState(timeoutMs = 15_000) {
            it.route.size > pausedRouteSize
        }
        val healthServicesDistanceAtFinish = RunningTrackingService.state.value.distanceMeters
        workoutDriver.openRunningControls()
        clickLabel("Finish run")

        require(device.wait(Until.hasObject(By.text("TREADMILL RUN")), 15_000)) {
            "The workout did not advance from the outdoor run to the treadmill run."
        }
        navigateToRunControls()
        delay(2_000)
        workoutDriver.openRunningControls()
        clickLabel("Finish run")
        require(device.wait(Until.hasObject(By.descContains("Edit treadmill distance")), 5_000)) {
            "Finishing the treadmill run did not show the distance edit affordance."
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
        var completed = emptyList<com.gabstra.myworkoutassistant.shared.WorkoutHistory>()
        while (System.currentTimeMillis() < deadline) {
            completed = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
                .filter { it.workoutId.toString() == RUNNING_WORKOUT_ID }
            if (completed.any { history -> history.runningResults.size == 2 }) break
            delay(250)
        }
        val history = completed.singleOrNull()
            ?: error("Completed running history was not persisted with two run results.")
        val outdoor = history.runningResults.single { it.exerciseId == OUTDOOR_EXERCISE_ID }
        val treadmill = history.runningResults.single { it.exerciseId == TREADMILL_EXERCISE_ID }
        require(outdoor.elapsedTimeMillis > 0) { "Outdoor run elapsed time was not recorded." }
        require(outdoor.route.size >= 2) {
            "Outdoor GPS route had ${outdoor.route.size} points; expected mocked GPS fixes to be recorded."
        }
        require(outdoor.route.all { point -> point.altitudeMeters?.let { it in -10_000.0..10_000.0 } ?: true }) {
            "Outdoor GPS route contains invalid altitude values: ${outdoor.route}"
        }
        val savedRouteDistanceMeters = routeDistanceMeters(outdoor.route)
        val expectedRouteDistanceMeters = routeDistanceMeters(INJECTED_GPS_ROUTE.map { (latitude, longitude) ->
            com.gabstra.myworkoutassistant.shared.running.RunningRoutePoint(
                latitude = latitude,
                longitude = longitude,
                elapsedTimeMillis = 0L,
            )
        })
        require(savedRouteDistanceMeters > 0.0) {
            "Mock GPS emitted route points, but their measured distance was zero. Route=${outdoor.route}"
        }
        require(savedRouteDistanceMeters in (expectedRouteDistanceMeters * 0.9)..(expectedRouteDistanceMeters * 1.1)) {
            "Saved GPS route measures $savedRouteDistanceMeters m, expected about " +
                "$expectedRouteDistanceMeters m from the injected coordinates. Route=${outdoor.route}"
        }
        require(outdoor.distanceMeters?.let {
            it in (expectedRouteDistanceMeters * 0.9)..(expectedRouteDistanceMeters * 1.1)
        } == true) {
            "Saved outdoor distance ${outdoor.distanceMeters} m does not match injected GPS route " +
                "distance $expectedRouteDistanceMeters m."
        }
        require(healthServicesDistanceAtFinish?.let { it > 0.0 } == true) {
            "Health Services did not report a distance metric during the GPS run."
        }
        require(outdoor.averagePaceSecondsPerKilometer?.let { it > 0.0 } == true) {
            "Outdoor average pace should be saved when route distance is available."
        }
        require(treadmill.elapsedTimeMillis > 0) { "Treadmill elapsed time was not recorded." }
        require(treadmill.distanceMeters?.let { it > 0.0 } == true) {
            "Treadmill distance correction was not saved."
        }
        require(treadmill.route.isEmpty()) { "Treadmill result should not contain a GPS route." }

        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }

    @Test
    fun outdoorRunWithoutGps_keepsTimerAndCompletesWithoutRoute() = runBlocking {
        setEmulatorLocationEnabled(false)
        try {
            startWorkout(RUNNING_PLAN_NAME)
            navigateToRunControls()
            waitForText("OUTDOOR RUN", 5_000)
            waitForTrackingState(timeoutMs = 10_000) { it.running }
            require(device.wait(Until.hasObject(By.desc("GPS unavailable; no route saved")), 12_000)) {
                "An outdoor run without GPS fixes must clearly report that no route is being recorded."
            }
            delay(2_000)
            require(RunningTrackingService.state.value.running) {
                "Missing GPS fixes should not stop the workout timer."
            }
            waitForTrackingState(timeoutMs = 15_000) {
                it.running && it.distanceMeters?.let { distance -> distance > 0.0 } == true
            }
            workoutDriver.openRunningControls()
            clickLabel("Finish run")
            finishTreadmillRun()

            val history = awaitCompletedRunningHistory()
            val outdoor = history.runningResults.single { it.exerciseId == OUTDOOR_EXERCISE_ID }
            val treadmill = history.runningResults.single { it.exerciseId == TREADMILL_EXERCISE_ID }
            require(outdoor.elapsedTimeMillis > 0) { "Outdoor elapsed time was not saved without GPS." }
            require(outdoor.route.isEmpty()) { "An outdoor run without a GPS fix must not save a route." }
            require(outdoor.distanceMeters?.let { it > 0.0 } == true) {
                "Health Services should save step-estimated outdoor distance when GPS is unavailable."
            }
            require(treadmill.route.isEmpty()) { "Treadmill runs must not save GPS routes." }
            syncCompletedHistoryToPhone()
        } finally {
            setEmulatorLocationEnabled(true)
        }
    }

    private suspend fun finishTreadmillRun() {
        require(device.wait(Until.hasObject(By.text("TREADMILL RUN")), 15_000)) {
            "The workout did not advance from the outdoor run to the treadmill run."
        }
        navigateToRunControls()
        delay(2_000)
        workoutDriver.openRunningControls()
        clickLabel("Finish run")
        require(device.wait(Until.hasObject(By.descContains("Edit treadmill distance")), 5_000)) {
            "Finishing the treadmill run did not show the distance edit affordance."
        }
        clickDescriptionContaining("Edit treadmill distance")
        require(device.wait(Until.hasObject(By.text(Pattern.compile("DISTANCE \\((km|mi)\\)"))), 5_000)) {
            "Treadmill distance adjustment controls did not open."
        }
        clickLabel("Add")
        clickLabel("Back")
        clickText("Save run")
        workoutDriver.waitForWorkoutCompletion(timeoutMs = 20_000)
    }

    private suspend fun awaitCompletedRunningHistory(): com.gabstra.myworkoutassistant.shared.WorkoutHistory {
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + 30_000
        while (System.currentTimeMillis() < deadline) {
            val history = db.workoutHistoryDao().getAllWorkoutHistoriesByIsDone(true)
                .singleOrNull { it.workoutId.toString() == RUNNING_WORKOUT_ID }
            if (history?.runningResults?.size == 2) return history
            delay(250)
        }
        error("Completed running history was not persisted with two run results.")
    }

    private suspend fun syncCompletedHistoryToPhone() {
        CrossDeviceWearSyncStateHelper.waitForCompletedHistoryAndEnqueueSync(context)
        CrossDeviceWearSyncStateHelper.waitForWearSyncMarker(context)
    }

    private fun clickText(text: String) {
        val target = device.wait(Until.findObject(By.text(text)), 15_000) ?: run {
            val hierarchy = File(context.cacheDir, "running_gps_missing_text.xml")
            device.dumpWindowHierarchy(hierarchy)
            device.takeScreenshot(File(context.cacheDir, "running_gps_missing_text.png"))
            val textNodes = device.findObjects(By.text(Pattern.compile(".+"))).joinToString { it.text }
            error("Timed out waiting for '$text' on the run screen. Visible text: $textNodes. Hierarchy: ${hierarchy.absolutePath}")
        }
        workoutDriver.clickObjectOrAncestor(target)
        device.waitForIdle()
    }

    private fun navigateToRunControls() {
        val observedText = mutableListOf<String>()
        repeat(5) {
            val startRun = device.wait(Until.findObject(By.desc("Start run")), 1_000)
                ?: device.wait(Until.findObject(By.text("Start run")), 250)
            if (startRun != null) {
                workoutDriver.clickObjectOrAncestor(startRun)
                device.waitForIdle()
                return
            }
            observedText += "page $it: " + device.findObjects(By.text(Pattern.compile(".+")))
                .joinToString { node -> node.text }
            workoutDriver.navigateToPagerPage(Direction.LEFT)
        }

        val visibleNodes = device.findObjects(By.clickable(true)).joinToString {
            "text=${it.text}, desc=${it.contentDescription}, bounds=${it.visibleBounds}"
        }
        val hierarchy = File(context.cacheDir, "running_gps_failure_hierarchy.xml")
        device.dumpWindowHierarchy(hierarchy)
        error("Could not navigate to run controls. Observed text: $observedText. Clickable nodes: $visibleNodes. Hierarchy: ${hierarchy.absolutePath}")
    }

    private fun clickLabel(label: String) {
        val target = device.wait(Until.findObject(By.desc(label)), 15_000) ?: run {
            val hierarchy = File(context.cacheDir, "running_gps_missing_label.xml")
            device.dumpWindowHierarchy(hierarchy)
            val clickableNodes = device.findObjects(By.clickable(true)).joinToString {
                "text=${it.text}, desc=${it.contentDescription}, bounds=${it.visibleBounds}"
            }
            device.takeScreenshot(File(context.cacheDir, "running_gps_missing_label.png"))
            error("Timed out waiting for '$label' on the run screen. Clickable nodes: $clickableNodes. Hierarchy: ${hierarchy.absolutePath}")
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

    private fun waitForText(text: String, timeoutMs: Long) {
        require(device.wait(Until.hasObject(By.text(text)), timeoutMs)) {
            "Expected '$text' in the running step."
        }
    }

    private suspend fun waitForTrackingState(
        timeoutMs: Long,
        predicate: (com.gabstra.myworkoutassistant.services.RunningTrackingState) -> Boolean,
    ) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (predicate(RunningTrackingService.state.value)) return
            delay(250)
        }
        error("Timed out waiting for run tracking state: ${RunningTrackingService.state.value}")
    }

    private fun setEmulatorLocationEnabled(enabled: Boolean) {
        val instrumentation = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation()
        val command = "cmd location set-location-enabled $enabled"
        val outputDescriptor = instrumentation.uiAutomation.executeShellCommand(command)
        val output = FileInputStream(outputDescriptor.fileDescriptor).bufferedReader().use { it.readText() }
        outputDescriptor.close()
        val stateDescriptor = instrumentation.uiAutomation.executeShellCommand("cmd location is-location-enabled")
        val isEnabled = FileInputStream(stateDescriptor.fileDescriptor).bufferedReader().use { it.readText().trim() }
        stateDescriptor.close()
        require(isEnabled.equals(enabled.toString(), ignoreCase = true)) {
            "Failed to set emulator location enabled=$enabled. Command output: $output, observed state: $isEnabled"
        }
    }

    private fun setMockLocationAppOp(allowed: Boolean) {
        val instrumentation = androidx.test.platform.app.InstrumentationRegistry.getInstrumentation()
        val mode = if (allowed) "allow" else "default"
        val descriptor = instrumentation.uiAutomation.executeShellCommand(
            "appops set ${context.packageName} android:mock_location $mode"
        )
        val output = FileInputStream(descriptor.fileDescriptor).bufferedReader().use { it.readText() }
        descriptor.close()
        require(output.isBlank()) { "Could not configure mock location app-op: $output" }
    }

    @Suppress("DEPRECATION")
    private fun addTestGpsProvider() {
        if (!testGpsProviderRegistered) {
            locationManager.addTestProvider(
                LocationManager.GPS_PROVIDER,
                false,
                true,
                false,
                false,
                true,
                true,
                true,
                Criteria.POWER_HIGH,
                Criteria.ACCURACY_FINE,
            )
            testGpsProviderRegistered = true
        }
        locationManager.setTestProviderEnabled(LocationManager.GPS_PROVIDER, true)
    }

    private fun removeTestGpsProvider() {
        if (!testGpsProviderRegistered) return
        locationManager.removeTestProvider(LocationManager.GPS_PROVIDER)
        testGpsProviderRegistered = false
    }

    private suspend fun injectGpsLocations(count: Int) {
        repeat(count) {
            val (latitude, longitude) = INJECTED_GPS_ROUTE[nextGpsFixIndex % INJECTED_GPS_ROUTE.size]
            nextGpsFixIndex++
            locationManager.setTestProviderLocation(
                LocationManager.GPS_PROVIDER,
                Location(LocationManager.GPS_PROVIDER).apply {
                    this.latitude = latitude
                    this.longitude = longitude
                    altitude = 5.0
                    accuracy = 4.0f
                    time = System.currentTimeMillis()
                    elapsedRealtimeNanos = SystemClock.elapsedRealtimeNanos()
                }
            )
            delay(1_500)
        }
    }

    private fun routeDistanceMeters(
        route: List<com.gabstra.myworkoutassistant.shared.running.RunningRoutePoint>,
    ): Double = route.zipWithNext().sumOf { (first, second) ->
        val latitudeDelta = Math.toRadians(second.latitude - first.latitude)
        val longitudeDelta = Math.toRadians(second.longitude - first.longitude)
        val haversine = kotlin.math.sin(latitudeDelta / 2).let { it * it } +
            kotlin.math.cos(Math.toRadians(first.latitude)) * kotlin.math.cos(Math.toRadians(second.latitude)) *
            kotlin.math.sin(longitudeDelta / 2).let { it * it }
        6_371_000.0 * 2 * kotlin.math.asin(kotlin.math.sqrt(haversine.coerceIn(0.0, 1.0)))
    }

    companion object {
        private val INJECTED_GPS_ROUTE = listOf(
            37.421900 to -122.084000,
            37.421980 to -122.083920,
            37.422060 to -122.083830,
            37.422140 to -122.083740,
            37.422220 to -122.083650,
            37.422300 to -122.083560,
        )
        private const val RUNNING_PLAN_NAME = "Cross Device Running Plan"
        private const val RUNNING_WORKOUT_ID = "65d1f21a-459c-4376-8a99-2fa1328f4f50"
        private const val OUTDOOR_EXERCISE_ID = "75398883-7cf8-42b3-8c44-0e8e394480f0"
        private const val TREADMILL_EXERCISE_ID = "5cba1938-3093-40fa-934e-5c63fd6af852"
    }
}
