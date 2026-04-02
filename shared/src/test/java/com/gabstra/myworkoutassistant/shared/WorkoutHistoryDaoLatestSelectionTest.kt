package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutHistoryDaoLatestSelectionTest {
    private lateinit var db: AppDatabase

    @Before
    fun setup() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        db = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
    }

    @After
    fun tearDown() {
        db.close()
    }

    @Test
    fun getLatestWorkoutHistoryByWorkoutId_prefersLaterStartTimeOnSameDay() = runBlocking {
        val workoutId = UUID.randomUUID()
        val globalId = UUID.randomUUID()
        val day = LocalDate.of(2026, 4, 1)
        val earlierHistory = history(
            workoutId = workoutId,
            globalId = globalId,
            startTime = LocalDateTime.of(day, LocalTime.of(9, 0)),
            version = 1u
        )
        val laterHistory = history(
            workoutId = workoutId,
            globalId = globalId,
            startTime = LocalDateTime.of(day, LocalTime.of(18, 0)),
            version = 1u
        )

        db.workoutHistoryDao().insertAll(earlierHistory, laterHistory)

        val latest = db.workoutHistoryDao().getLatestWorkoutHistoryByWorkoutId(workoutId)

        assertEquals(laterHistory.id, latest?.id)
    }

    @Test
    fun getLatestWorkoutHistoryByWorkoutId_prefersHigherVersionWhenStartTimeMatches() = runBlocking {
        val workoutId = UUID.randomUUID()
        val globalId = UUID.randomUUID()
        val startTime = LocalDateTime.of(2026, 4, 1, 18, 0)
        val olderVersion = history(
            workoutId = workoutId,
            globalId = globalId,
            startTime = startTime,
            version = 1u
        )
        val newerVersion = history(
            workoutId = workoutId,
            globalId = globalId,
            startTime = startTime,
            version = 3u
        )

        db.workoutHistoryDao().insertAll(olderVersion, newerVersion)

        val latest = db.workoutHistoryDao().getLatestWorkoutHistoryByWorkoutId(workoutId)

        assertEquals(newerVersion.id, latest?.id)
    }

    private fun history(
        workoutId: UUID,
        globalId: UUID,
        startTime: LocalDateTime,
        version: UInt
    ): WorkoutHistory = WorkoutHistory(
        id = UUID.randomUUID(),
        workoutId = workoutId,
        date = startTime.toLocalDate(),
        time = startTime.toLocalTime(),
        startTime = startTime,
        duration = 600,
        heartBeatRecords = emptyList(),
        isDone = true,
        hasBeenSentToHealth = false,
        globalId = globalId,
        version = version
    )
}
