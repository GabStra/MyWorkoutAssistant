package com.gabstra.myworkoutassistant.shared.workout.persistence

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.workout.model.SessionOwnerDevice
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutRecordServiceTest {

    private lateinit var db: AppDatabase
    private lateinit var service: WorkoutRecordService

    @Before
    fun setup() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        service = WorkoutRecordService(
            workoutRecordDao = { db.workoutRecordDao() },
            workoutHistoryDao = { db.workoutHistoryDao() }
        )
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun resolveWorkoutRecord_throwsWhenMultipleRowsExistForWorkoutId() = runBlocking {
        val workoutId = UUID.randomUUID()
        val history1 = insertHistory(workoutId, 10)
        val history2 = insertHistory(workoutId, 11)
        db.workoutRecordDao().insertAll(
            record(workoutId, history1.id, 0u, 1u),
            record(workoutId, history2.id, 1u, 2u)
        )

        try {
            service.resolveWorkoutRecord(workoutId)
            fail("Expected resolveWorkoutRecord to reject duplicate rows for the same workoutId.")
        } catch (_: IllegalArgumentException) {
        }
    }

    @Test
    fun upsertWorkoutRecord_replacesExistingRowsForWorkoutId() = runBlocking {
        val workoutId = UUID.randomUUID()
        val history = insertHistory(workoutId, 10)
        db.workoutRecordDao().insertAll(
            record(workoutId, history.id, 0u, 1u),
            record(workoutId, history.id, 1u, 2u)
        )

        val updated = service.upsertWorkoutRecord(
            existingRecord = null,
            workoutId = workoutId,
            workoutHistoryId = history.id,
            exerciseId = UUID.randomUUID(),
            setIndex = 2u,
            ownerDevice = SessionOwnerDevice.WEAR,
            lastActiveSyncAt = LocalDateTime.now(),
            lastKnownSessionState = "Rest"
        )

        val rows = db.workoutRecordDao().getWorkoutRecordsByWorkoutId(workoutId)
        assertEquals(1, rows.size)
        assertEquals(updated?.id, rows.single().id)
        assertEquals(2u, rows.single().setIndex)
    }

    @Test
    fun adoptWorkoutRecord_replacesExistingRowsForWorkoutId() = runBlocking {
        val workoutId = UUID.randomUUID()
        val history = insertHistory(workoutId, 10)
        val existing = record(workoutId, history.id, 0u, 1u)
        db.workoutRecordDao().insertAll(existing, record(workoutId, history.id, 1u, 2u))

        val adopted = service.adoptWorkoutRecord(
            existingRecord = existing,
            ownerDevice = SessionOwnerDevice.WEAR,
            lastActiveSyncAt = LocalDateTime.now(),
            lastKnownSessionState = "RESUMED"
        )

        val rows = db.workoutRecordDao().getWorkoutRecordsByWorkoutId(workoutId)
        assertEquals(1, rows.size)
        assertEquals(adopted.id, rows.single().id)
        assertEquals(adopted.activeSessionRevision, rows.single().activeSessionRevision)
    }

    private suspend fun insertHistory(workoutId: UUID, startHour: Int): WorkoutHistory {
        val date = LocalDate.now()
        val history = WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = workoutId,
            date = date,
            duration = 3600,
            heartBeatRecords = emptyList(),
            time = LocalTime.of(startHour, 0),
            startTime = LocalDateTime.of(date, LocalTime.of(startHour, 0)),
            isDone = false,
            hasBeenSentToHealth = false,
            globalId = UUID.randomUUID()
        )
        db.workoutHistoryDao().insert(history)
        return history
    }

    private fun record(
        workoutId: UUID,
        workoutHistoryId: UUID,
        setIndex: UInt,
        activeSessionRevision: UInt
    ): WorkoutRecord = WorkoutRecord(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        workoutHistoryId = workoutHistoryId,
        setIndex = setIndex,
        exerciseId = UUID.randomUUID(),
        ownerDevice = SessionOwnerDevice.WEAR.name,
        lastActiveSyncAt = LocalDateTime.now(),
        activeSessionRevision = activeSessionRevision,
        lastKnownSessionState = "Set"
    )
}
