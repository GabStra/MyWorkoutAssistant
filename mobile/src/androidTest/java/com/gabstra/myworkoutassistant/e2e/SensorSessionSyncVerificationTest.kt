package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncAssertions
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus
import java.io.File
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SensorSessionSyncVerificationTest {
    private fun resolvedSyncTimeoutMs(): Long = 180_000

    /**
     * Verifies the /sensorSession chunked transfer end to end: after the cross-device producer
     * completes a workout on the watch, the recorded sensor session must arrive on the phone with
     * its Room rows, raw chunk files, and ground-truth reps in events.csv.
     */
    @Test
    fun crossDeviceSync_sensorSessionArrivesOnPhoneWithGroundTruth() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)

        CrossDeviceSyncAssertions.waitForCheckpoint(
            context = context,
            checkpoint = CrossDeviceSyncAssertions.finalCheckpoint,
            timeoutMs = resolvedSyncTimeoutMs()
        )
        val historyId = db.workoutHistoryDao().getAllWorkoutHistories()
            .firstOrNull {
                it.isDone && it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID
            }?.id
            ?: error("Cross-device history arrived but could not be resolved for session correlation")

        val session = pollFor {
            db.motionCaptureSessionDao()
                .getLatestByStatus(MotionCaptureSessionStatus.COMPLETED.name)
                ?.takeIf { it.workoutHistoryId == historyId }
        } ?: error(
            "No COMPLETED sensor session synced for workout history $historyId within " +
                "${resolvedSyncTimeoutMs()}ms"
        )

        val segments = db.motionCaptureSyncDao()
            .observeSegmentsBySessionId(session.id)
            .first()
        assertTrue(
            "Sensor session ${session.id} arrived without segments",
            segments.isNotEmpty()
        )

        val sessionDirectory = File(
            context.filesDir,
            "motion_capture/sessions/${session.sessionDirectoryName}"
        )
        assertTrue(
            "Session directory missing on phone: $sessionDirectory",
            sessionDirectory.isDirectory
        )
        val chunkFiles = sessionDirectory.listFiles { file ->
            file.isFile && file.name.startsWith("chunk_")
        }.orEmpty()
        assertTrue(
            "No chunk files transferred for sensor session ${session.id}",
            chunkFiles.isNotEmpty()
        )

        val eventsFile = File(sessionDirectory, "events.csv")
        assertTrue("events.csv missing from transferred session", eventsFile.exists())
        val eventsText = eventsFile.readText()
        assertTrue(
            "events.csv header is missing the actualReps ground-truth column",
            eventsText.contains("actualReps")
        )
        val setCompletedWithReps = eventsText.lineSequence().any { line ->
            line.startsWith("set_completed,") && line.substringAfterLast(',').isNotEmpty() &&
                line.substringAfterLast(',').toIntOrNull() != null
        }
        assertTrue(
            "No SET_COMPLETED event with actualReps found in events.csv",
            setCompletedWithReps
        )
    }

    private suspend fun <T> pollFor(
        intervalMs: Long = 1_000,
        timeoutMs: Long = resolvedSyncTimeoutMs(),
        condition: suspend () -> T?
    ): T? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            condition()?.let { return it }
            delay(intervalMs)
        }
        return condition()
    }
}
