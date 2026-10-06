package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CompletionWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearWorkoutStateMutationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureJson
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureLabelKind
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionEntity
import com.gabstra.myworkoutassistant.shared.motion.MotionCaptureSessionStatus
import com.gabstra.myworkoutassistant.shared.motion.MotionSensorType
import java.io.File
import java.util.UUID
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearMotionCaptureAutoStartE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    override fun prepareAppStateBeforeLaunch() {
        clearMotionCaptureState()
        CompletionWorkoutStoreFixture.setupWorkoutStore(context)
    }

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun motionCapture_autoStarts_recordsSetSegment_completesAndGzipsWithWorkout() = runBlocking {
        requireNoActiveSession("capture session existed before the workout started")

        startWorkout(CompletionWorkoutStoreFixture.getWorkoutName())

        val activeSession = pollForSessionStatus(MotionCaptureSessionStatus.ACTIVE, timeoutMs = 20_000)
            ?: error("No ACTIVE motion capture session started with the workout")

        val setCompleted = WearWorkoutStateMutationHelper.completeCurrentSet(
            device = device,
            context = context,
            timeoutMs = 20_000
        )
        require(setCompleted) { "Failed to complete the single workout set" }

        assertExerciseSegmentRecorded(activeSession.id)

        workoutDriver.waitForWorkoutCompletion(timeoutMs = 30_000)

        val completedSession = pollForSessionStatus(MotionCaptureSessionStatus.COMPLETED, timeoutMs = 20_000)
            ?: error("Motion capture session did not reach COMPLETED after the workout finished")

        awaitGzippedChunks(completedSession.sessionDirectoryName, timeoutMs = 15_000)
        assertObservedSensorsPersisted(completedSession.sensorConfigJson)
    }

    private fun clearMotionCaptureState() = runBlocking {
        val db = AppDatabase.getDatabase(context)
        db.openHelper.writableDatabase.execSQL("DELETE FROM motion_capture_segment")
        db.openHelper.writableDatabase.execSQL("DELETE FROM motion_capture_session")
        File(context.filesDir, "motion_capture").deleteRecursively()
    }

    private suspend fun requireNoActiveSession(message: String) {
        val active = AppDatabase.getDatabase(context).motionCaptureSessionDao()
            .getLatestByStatus(MotionCaptureSessionStatus.ACTIVE.name)
        require(active == null) { message }
    }

    private suspend fun pollForSessionStatus(
        status: MotionCaptureSessionStatus,
        timeoutMs: Long
    ): MotionCaptureSessionEntity? {
        val deadline = System.currentTimeMillis() + timeoutMs
        val dao = AppDatabase.getDatabase(context).motionCaptureSessionDao()
        while (System.currentTimeMillis() < deadline) {
            dao.getLatestByStatus(status.name)?.let { return it }
            delay(250)
        }
        return null
    }

    private suspend fun assertExerciseSegmentRecorded(sessionId: UUID) {
        val deadline = System.currentTimeMillis() + 10_000
        val segmentDao = AppDatabase.getDatabase(context).motionCaptureSegmentDao()
        while (System.currentTimeMillis() < deadline) {
            val hasExerciseSegment = segmentDao.getBySessionId(sessionId).any { entity ->
                val labelJson = entity.correctedLabelJson ?: entity.autoLabelJson
                MotionCaptureJson.labelFromJson(labelJson).kind == MotionCaptureLabelKind.EXERCISE
            }
            if (hasExerciseSegment) {
                return
            }
            delay(250)
        }
        error("No EXERCISE segment was recorded for the completed set")
    }

    /**
     * The session row is marked COMPLETED before chunk compression finishes, so wait for the
     * gzip outcome instead of asserting at first sight of the status row. The three terminal
     * errors distinguish a compression failure from a capture that never wrote any samples.
     */
    private fun awaitGzippedChunks(sessionDirectoryName: String, timeoutMs: Long) {
        val sessionDirectory = File(context.filesDir, "motion_capture/sessions/$sessionDirectoryName")
        require(sessionDirectory.isDirectory) { "Session directory missing: $sessionDirectory" }

        val deadline = System.currentTimeMillis() + timeoutMs
        var sawGzippedChunk = false
        var sawPlainChunk = false
        while (System.currentTimeMillis() < deadline) {
            val gzipped = sessionDirectory.listFiles { file ->
                file.isFile && file.name.startsWith("chunk_") && file.name.endsWith(".csv.gz")
            }.orEmpty()
            val plain = sessionDirectory.listFiles { file ->
                file.isFile && file.name.startsWith("chunk_") && file.name.endsWith(".csv")
            }.orEmpty()
            sawGzippedChunk = sawGzippedChunk || gzipped.isNotEmpty()
            sawPlainChunk = sawPlainChunk || plain.isNotEmpty()
            if (sawGzippedChunk && plain.isEmpty()) {
                require(File(sessionDirectory, "events.csv").exists()) { "events.csv missing from session directory" }
                return
            }
            Thread.sleep(250)
        }
        error(
            when {
                sawGzippedChunk -> "Plain chunk files remained after the gzip deadline"
                sawPlainChunk -> "Chunk files were never gzipped after session completion"
                else -> "No chunk files were ever written - zero sensor samples captured"
            }
        )
    }

    private fun assertObservedSensorsPersisted(sensorConfigJson: String) {
        val config = MotionCaptureJson.sensorConfigFromJson(sensorConfigJson)
        val observed = requireNotNull(config.observedSensors) {
            "observedSensors missing from session sensor config"
        }
        require(MotionSensorType.ACCELEROMETER in observed) {
            "Accelerometer missing from observed sensors: $observed"
        }
        require(MotionSensorType.STEP_COUNTER !in observed) {
            "Step counter must not be captured by default: $observed"
        }
    }
}
