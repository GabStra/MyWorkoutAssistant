package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.gabstra.myworkoutassistant.e2e.helpers.WorkoutHeartbeatCrossDeviceObservationState
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.datalayer.DEFAULT_WORKOUT_SESSION_HEARTBEAT_INTERVAL_MS
import com.gabstra.myworkoutassistant.shared.workout.model.ACTIVE_SESSION_STALE_TIMEOUT_MS
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionStatus
import com.gabstra.myworkoutassistant.shared.workout.model.isWorkoutRecordFresh
import com.gabstra.myworkoutassistant.shared.workout.model.ownerDeviceOrDefault
import com.gabstra.myworkoutassistant.shared.workout.model.resolveWorkoutSessionStatus
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime

@RunWith(AndroidJUnit4::class)
class WorkoutHeartbeatCrossDeviceObservationTest {

    private companion object {
        const val HISTORY_RECENCY_MINUTES = 120L
        const val POLL_INTERVAL_MS = 5_000L
        const val START_TIMEOUT_MS = 45_000L
        val OBSERVATION_WINDOW_MS = ACTIVE_SESSION_STALE_TIMEOUT_MS + 15_000L
    }

    private fun requireLiveObservationOrSkip() {
        assumeTrue(
            "Requires live cross-device sync orchestration. Run via run_cross_device_sync_e2e.ps1.",
            CrossDeviceSyncTestPrerequisites.isLiveObserverRun()
        )
    }

    @Test
    fun crossDeviceSync_activeWearWorkoutNeverTurnsIntoWatchDisconnectedWhileHeartbeatsArrive() = runBlocking {
        requireLiveObservationOrSkip()

        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        WorkoutHeartbeatCrossDeviceObservationState.clear(context)

        val db = AppDatabase.getDatabase(context)
        val initialPair = waitForActiveWearSession(db, timeoutMs = START_TIMEOUT_MS)
        var lastSyncAt = initialPair.second.lastActiveSyncAt
        var syncAdvanceCount = 0
        val observationDeadline = System.currentTimeMillis() + OBSERVATION_WINDOW_MS

        while (System.currentTimeMillis() < observationDeadline) {
            delay(POLL_INTERVAL_MS)
            val (history, record) = requireActiveWearSession(db)
            assertSessionStillFresh(history, record)
            val currentSyncAt = record.lastActiveSyncAt
            if (currentSyncAt != null && lastSyncAt != null && currentSyncAt.isAfter(lastSyncAt)) {
                syncAdvanceCount++
            }
            if (currentSyncAt != null) {
                lastSyncAt = currentSyncAt
            }
        }

        assertTrue(
            "Expected lastActiveSyncAt to advance while the Wear workout stayed active. " +
                "Observed window=${OBSERVATION_WINDOW_MS}ms staleTimeout=${ACTIVE_SESSION_STALE_TIMEOUT_MS}ms " +
                "heartbeatInterval=${DEFAULT_WORKOUT_SESSION_HEARTBEAT_INTERVAL_MS}ms.",
            syncAdvanceCount > 0
        )

        WorkoutHeartbeatCrossDeviceObservationState.markPassed(
            context = context,
            details = "Observed active Wear session for ${OBSERVATION_WINDOW_MS}ms with " +
                "$syncAdvanceCount lastActiveSyncAt advance(s)."
        )
    }

    private suspend fun waitForActiveWearSession(
        db: AppDatabase,
        timeoutMs: Long
    ): Pair<WorkoutHistory, WorkoutRecord> {
        val deadline = System.currentTimeMillis() + timeoutMs
        var lastError: AssertionError? = null

        while (System.currentTimeMillis() < deadline) {
            try {
                return requireActiveWearSession(db)
            } catch (error: AssertionError) {
                lastError = error
            }
            delay(500)
        }

        throw AssertionError(
            "Timed out waiting for an active Wear-owned cross-device session. " +
                (lastError?.message ?: "")
        )
    }

    private suspend fun requireActiveWearSession(
        db: AppDatabase
    ): Pair<WorkoutHistory, WorkoutRecord> {
        val history = db.workoutHistoryDao()
            .getAllWorkoutHistories()
            .filter {
                !it.isDone &&
                    it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID &&
                    it.globalId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                    Duration.between(it.startTime, LocalDateTime.now()).toMinutes() in 0..HISTORY_RECENCY_MINUTES
            }
            .maxByOrNull { it.version.toLong() }
            ?: throw AssertionError("No recent unfinished cross-device workout history found on phone.")

        val record = db.workoutRecordDao()
            .getWorkoutRecordByWorkoutId(CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID)
            ?: throw AssertionError("Expected an active workout record for the Wear-owned session.")

        if (record.workoutHistoryId != history.id) {
            throw AssertionError(
                "Workout record points to ${record.workoutHistoryId}, expected ${history.id}."
            )
        }

        assertSessionStillFresh(history, record)
        return history to record
    }

    private fun assertSessionStillFresh(
        history: WorkoutHistory,
        record: WorkoutRecord
    ) {
        if (record.ownerDeviceOrDefault() != SessionOwnerDevice.WEAR) {
            throw AssertionError("Expected Wear-owned workout record, found ${record.ownerDevice}.")
        }
        if (!isWorkoutRecordFresh(record)) {
            throw AssertionError(
                "Workout record became stale. lastActiveSyncAt=${record.lastActiveSyncAt}."
            )
        }
        val status = resolveWorkoutSessionStatus(history, record)
        if (status != WorkoutSessionStatus.IN_PROGRESS_ON_WEAR) {
            throw AssertionError(
                "Expected ${WorkoutSessionStatus.IN_PROGRESS_ON_WEAR}, found $status."
            )
        }
    }
}
