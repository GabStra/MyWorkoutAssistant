package com.gabstra.myworkoutassistant.e2e

import android.content.ContentValues
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.driver.PhoneAppDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.createAppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSONPrettyPrint
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import java.io.File
import java.util.regex.Pattern
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class RunningWorkoutSyncVerificationTest {
    @Test
    fun crossDeviceSync_preservesGpsRunMetricsAndRoute() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val completedHistory = awaitCompletedRunningHistory(context)

        assertEquals(2, completedHistory.runningResults.size)
        val outdoor = completedHistory.runningResults.single { it.exerciseId == CrossDeviceSyncPhoneWorkoutStoreFixture.OUTDOOR_RUN_EXERCISE_ID.toString() }
        val treadmill = completedHistory.runningResults.single { it.exerciseId == CrossDeviceSyncPhoneWorkoutStoreFixture.TREADMILL_RUN_EXERCISE_ID.toString() }
        assertTrue("Outdoor elapsed time should be retained", outdoor.elapsedTimeMillis > 0)
        assertTrue("Outdoor route points should be retained", outdoor.route.size >= 2)
        assertTrue("Route coordinates should be finite", outdoor.route.all { it.latitude.isFinite() && it.longitude.isFinite() })
        assertTrue(
            "Route altitudes should be absent or within geographic bounds",
            outdoor.route.all { point -> point.altitudeMeters?.let { it in -10_000.0..10_000.0 } ?: true },
        )
        assertTrue(
            "Injected emulator GPS coordinates should reach phone history",
            outdoor.route.any { point ->
                point.latitude in 37.4218..37.4224 && point.longitude in -122.0841..-122.0834
            },
        )
        assertTrue("Treadmill elapsed time should be retained", treadmill.elapsedTimeMillis > 0)
        assertTrue("Treadmill correction should be retained", (treadmill.distanceMeters ?: 0.0) > 0.0)
        assertTrue("Treadmill runs should not contain a route", treadmill.route.isEmpty())

        verifyGpsRouteIsVisibleInPhoneHistory(context)
        verifyGpsHistoryBackupRestoreAndDeletion(context, completedHistory)
    }

    @Test
    fun crossDeviceSync_preservesOutdoorMetricsWithoutGpsRoute() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val completedHistory = awaitCompletedRunningHistory(context)

        assertEquals(2, completedHistory.runningResults.size)
        val outdoor = completedHistory.runningResults.single {
            it.exerciseId == CrossDeviceSyncPhoneWorkoutStoreFixture.OUTDOOR_RUN_EXERCISE_ID.toString()
        }
        val treadmill = completedHistory.runningResults.single {
            it.exerciseId == CrossDeviceSyncPhoneWorkoutStoreFixture.TREADMILL_RUN_EXERCISE_ID.toString()
        }
        assertTrue("Outdoor elapsed time should sync without GPS", outdoor.elapsedTimeMillis > 0)
        assertTrue("Unavailable or denied GPS must not sync route points", outdoor.route.isEmpty())
        assertTrue("Treadmill elapsed time should be retained", treadmill.elapsedTimeMillis > 0)
        assertTrue("Treadmill distance correction should be retained", (treadmill.distanceMeters ?: 0.0) > 0.0)
        assertTrue("Treadmill runs should not contain a route", treadmill.route.isEmpty())
    }

    private suspend fun awaitCompletedRunningHistory(
        context: android.content.Context,
    ): com.gabstra.myworkoutassistant.shared.WorkoutHistory {
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + 60_000
        var history = db.workoutHistoryDao().getAllWorkoutHistories().firstOrNull {
            it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.RUNNING_PLAN_WORKOUT_ID && it.isDone
        }
        while (history == null && System.currentTimeMillis() < deadline) {
            delay(500)
            history = db.workoutHistoryDao().getAllWorkoutHistories().firstOrNull {
                it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.RUNNING_PLAN_WORKOUT_ID && it.isDone
            }
        }
        return requireNotNull(history) { "Completed running workout history did not sync to the phone." }
    }

    private fun verifyGpsRouteIsVisibleInPhoneHistory(context: android.content.Context) {
        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val appDriver = PhoneAppDriver(device, context)
        appDriver.launchAppFromHome()
        appDriver.grantHealthConnectPermissionsForE2E()
        val workoutsTab = device.wait(Until.findObject(By.text("Workouts")), 10_000)
            ?: error("Phone home screen did not expose the Workouts tab.")
        workoutsTab.click()
        device.waitForIdle(1_000)

        val workoutCard = device.wait(
            Until.findObject(By.desc("Open workout: ${CrossDeviceSyncPhoneWorkoutStoreFixture.RUNNING_PLAN_WORKOUT_NAME}")),
            15_000,
        ) ?: run {
            val hierarchy = File(context.cacheDir, "running_history_workout_missing.xml")
            device.dumpWindowHierarchy(hierarchy)
            val visibleText = device.findObjects(By.text(Pattern.compile(".+"))).joinToString { it.text }
            error("Synced running workout was not visible in the phone workout list. Visible text=$visibleText, hierarchy=${hierarchy.absolutePath}")
        }
        clickClickableAncestor(workoutCard)

        val historiesTab = device.wait(Until.findObject(By.text("Histories")), 15_000) ?: run {
            val hierarchy = File(context.cacheDir, "running_history_tab_missing.xml")
            device.dumpWindowHierarchy(hierarchy)
            val visibleText = device.findObjects(By.text(Pattern.compile(".+"))).joinToString { it.text }
            error("Workout detail did not expose the Histories tab on phone. Visible text=$visibleText, hierarchy=${hierarchy.absolutePath}")
        }
        historiesTab.click()
        device.waitForIdle(1_000)

        val routeDescription = By.desc("GPS route line with start and finish markers")
        var routeCanvas = device.wait(Until.findObject(routeDescription), 5_000)
        repeat(6) {
            if (routeCanvas == null) {
                val scrollable = device.findObject(By.scrollable(true))
                if (scrollable != null) {
                    runCatching { scrollable.scroll(Direction.DOWN, 0.8f) }
                }
                device.waitForIdle(300)
                routeCanvas = device.findObject(routeDescription)
            }
        }
        require(routeCanvas != null) {
            "Phone running history did not render the synced GPS route line and start/finish markers."
        }
        assertTrue(
            "Phone history should label route endpoints",
            device.wait(Until.hasObject(By.textContains("Start")), 3_000) &&
                device.wait(Until.hasObject(By.textContains("Finish")), 3_000),
        )
    }

    private suspend fun verifyGpsHistoryBackupRestoreAndDeletion(
        context: android.content.Context,
        expectedHistory: com.gabstra.myworkoutassistant.shared.WorkoutHistory,
    ) {
        val db = AppDatabase.getDatabase(context)
        val appBackup = requireNotNull(
            createAppBackup(
                workoutStore = WorkoutStoreRepository(context.filesDir).getWorkoutStore(),
                db = db,
                context = context,
            ),
        ) { "Production backup creation returned no app backup." }
        val backedUpHistory = appBackup.WorkoutHistories.single { it.id == expectedHistory.id }
        assertEquals("Backup must preserve the complete GPS history record", expectedHistory, backedUpHistory)

        val backupFileName = "running_gps_history_e2e_backup.json"
        val backupJson = fromAppBackupToJSONPrettyPrint(appBackup)
        val parsedBackup = fromJSONtoAppBackup(backupJson)
        assertEquals(
            "Backup JSON round-trip must preserve GPS results and route points",
            expectedHistory,
            parsedBackup.WorkoutHistories.single { it.id == expectedHistory.id },
        )
        val backupUri = stageBackupInDownloads(context, backupFileName, backupJson)

        val device = UiDevice.getInstance(InstrumentationRegistry.getInstrumentation())
        val driver = PhoneAppDriver(device, context)
        driver.launchAppFromHome()
        device.wait(Until.findObject(By.text("Workouts")), 10_000)?.click()
            ?: error("Phone home screen did not expose the Workouts tab before history deletion.")
        device.waitForIdle(500)
        openWorkoutDataMenu(device)
        device.wait(Until.findObject(By.text("Clear workout history")), 5_000)?.click()
            ?: error("Data menu did not expose Clear workout history.")
        device.wait(Until.findObject(By.text("Clear")), 5_000)?.click()
            ?: error("Clear history confirmation did not expose Clear.")
        device.waitForIdle(1_000)
        val deletedDeadline = System.currentTimeMillis() + 15_000
        while (db.workoutHistoryDao().getAllWorkoutHistories().any { it.id == expectedHistory.id } &&
            System.currentTimeMillis() < deletedDeadline
        ) {
            delay(250)
        }
        assertTrue(
            "Clearing workout history through the phone UI must delete the GPS route with its history record",
            db.workoutHistoryDao().getAllWorkoutHistories().none { it.id == expectedHistory.id },
        )

        device.wait(Until.findObject(By.desc("Menu")), 5_000)?.click()
            ?: error("Menu button not found after clearing workout history.")
        device.waitForIdle(500)
        device.wait(Until.findObject(By.text("Data")), 5_000)?.click()
            ?: error("Menu did not expose Data after clearing workout history.")
        device.waitForIdle(400)
        device.wait(Until.findObject(By.text("Restore backup")), 5_000)?.click()
            ?: error("Data menu did not expose Restore backup.")
        device.waitForIdle(1_000)
        driver.restoreBackupThroughFilePicker(
            backupFileName = backupFileName,
            backupFileNamePrefix = "running_gps_history_e2e_backup",
        )

        val restoreDeadline = System.currentTimeMillis() + 30_000
        var restoredHistory = db.workoutHistoryDao().getAllWorkoutHistories()
            .firstOrNull { it.id == expectedHistory.id }
        while (restoredHistory == null && System.currentTimeMillis() < restoreDeadline) {
            delay(500)
            restoredHistory = db.workoutHistoryDao().getAllWorkoutHistories()
                .firstOrNull { it.id == expectedHistory.id }
        }
        assertEquals("Restoring the production backup must recover route points and run metrics", expectedHistory, restoredHistory)
        context.contentResolver.delete(backupUri, null, null)
    }

    private fun stageBackupInDownloads(
        context: android.content.Context,
        fileName: String,
        json: String,
    ): android.net.Uri {
        val resolver = context.contentResolver
        resolver.delete(
            MediaStore.Downloads.EXTERNAL_CONTENT_URI,
            "${MediaStore.Downloads.DISPLAY_NAME} = ?",
            arrayOf(fileName),
        )
        val values = ContentValues().apply {
            put(MediaStore.Downloads.DISPLAY_NAME, fileName)
            put(MediaStore.Downloads.MIME_TYPE, "application/json")
            put(MediaStore.Downloads.RELATIVE_PATH, Environment.DIRECTORY_DOWNLOADS)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
        }
        val uri = requireNotNull(resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values)) {
            "Could not stage GPS backup in Downloads for the Restore picker."
        }
        try {
            resolver.openOutputStream(uri)?.use { output -> output.write(json.toByteArray()) }
                ?: error("Could not write the staged GPS backup.")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                resolver.update(
                    uri,
                    ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) },
                    null,
                    null,
                )
            }
        } catch (error: Throwable) {
            resolver.delete(uri, null, null)
            throw error
        }
        return uri
    }

    private fun openWorkoutDataMenu(device: UiDevice) {
        device.wait(Until.findObject(By.desc("Menu")), 5_000)?.click()
            ?: error("Menu button not found before clearing workout history.")
        device.waitForIdle(500)
        device.wait(Until.findObject(By.text("Data")), 5_000)?.click()
            ?: error("Menu did not expose Data before clearing workout history.")
        device.waitForIdle(400)
    }

    private fun clickClickableAncestor(obj: androidx.test.uiautomator.UiObject2) {
        var target: androidx.test.uiautomator.UiObject2? = obj
        while (target != null && !target.isClickable) {
            target = target.parent
        }
        (target ?: error("Workout card has no clickable parent.")).click()
    }
}
