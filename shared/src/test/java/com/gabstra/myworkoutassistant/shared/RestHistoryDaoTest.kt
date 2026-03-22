package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class RestHistoryDaoTest {

    private lateinit var context: Context
    private lateinit var database: AppDatabase

    @Before
    fun setup() {
        context = ApplicationProvider.getApplicationContext()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun deleteWorkoutHistory_cascadesRestHistory() = runBlocking {
        val workoutId = UUID.randomUUID()
        val globalId = UUID.randomUUID()
        val historyId = UUID.randomUUID()
        val workoutHistory = WorkoutHistory(
            id = historyId,
            workoutId = workoutId,
            date = LocalDate.of(2026, 3, 22),
            time = LocalTime.of(10, 0),
            startTime = LocalDateTime.of(2026, 3, 22, 10, 0),
            duration = 3600,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = globalId
        )
        database.workoutHistoryDao().insert(workoutHistory)

        val restId = UUID.randomUUID()
        val rest = RestHistory(
            id = restId,
            workoutHistoryId = historyId,
            scope = RestHistoryScope.INTRA_EXERCISE,
            executionSequence = 1u,
            setData = RestSetData(90, 90, SetSubCategory.WorkSet),
            startTime = LocalDateTime.of(2026, 3, 22, 10, 5),
            endTime = LocalDateTime.of(2026, 3, 22, 10, 6, 30),
            workoutComponentId = null,
            exerciseId = UUID.randomUUID(),
            restSetId = UUID.randomUUID(),
            order = 0u
        )
        database.restHistoryDao().insert(rest)

        assertEquals(1, database.restHistoryDao().getByWorkoutHistoryId(historyId).size)

        database.workoutHistoryDao().deleteById(historyId)

        assertTrue(database.restHistoryDao().getByWorkoutHistoryId(historyId).isEmpty())
    }

    @Test
    fun getByWorkoutHistoryIdOrdered_sortsByExecutionSequence() = runBlocking {
        val workoutId = UUID.randomUUID()
        val globalId = UUID.randomUUID()
        val historyId = UUID.randomUUID()
        database.workoutHistoryDao().insert(
            WorkoutHistory(
                id = historyId,
                workoutId = workoutId,
                date = LocalDate.of(2026, 3, 22),
                time = LocalTime.of(10, 0),
                startTime = LocalDateTime.of(2026, 3, 22, 10, 0),
                duration = 3600,
                heartBeatRecords = emptyList(),
                isDone = true,
                hasBeenSentToHealth = false,
                globalId = globalId
            )
        )

        val r2 = restRow(historyId, UUID.randomUUID(), 2u)
        val r1 = restRow(historyId, UUID.randomUUID(), 1u)
        database.restHistoryDao().insert(r2)
        database.restHistoryDao().insert(r1)

        val ordered = database.restHistoryDao().getByWorkoutHistoryIdOrdered(historyId)
        assertEquals(listOf(r1.id, r2.id), ordered.map { it.id })
    }

    private fun restRow(workoutHistoryId: UUID, id: UUID, seq: UInt): RestHistory = RestHistory(
        id = id,
        workoutHistoryId = workoutHistoryId,
        scope = RestHistoryScope.BETWEEN_WORKOUT_COMPONENTS,
        executionSequence = seq,
        setData = RestSetData(30, 30, SetSubCategory.WorkSet),
        startTime = LocalDateTime.of(2026, 3, 22, 10, 0),
        endTime = LocalDateTime.of(2026, 3, 22, 10, 0, 30),
        workoutComponentId = UUID.randomUUID(),
        exerciseId = null,
        restSetId = UUID.randomUUID(),
        order = 0u
    )
}
