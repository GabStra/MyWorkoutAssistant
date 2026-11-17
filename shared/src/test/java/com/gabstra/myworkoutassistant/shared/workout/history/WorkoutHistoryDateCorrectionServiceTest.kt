package com.gabstra.myworkoutassistant.shared.workout.history

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Test
import org.junit.Assert.assertTrue
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutHistoryDateCorrectionServiceTest {
    private lateinit var database: AppDatabase
    private val activeProfileId = "date-correction-profile"
    private val profileId = activeProfileId
    private val historyId = UUID.randomUUID()
    private val originalDate = LocalDate.of(2026, 11, 13)
    private val correctedDate = LocalDate.of(2026, 11, 12)

    @Before
    fun setUp() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun correctsDateInPlaceAndPreservesHistoryAndSetRows() = runBlocking {
        val original = history(
            id = historyId,
            origin = WorkoutHistoryOrigin.USER_IMPORTED,
            startTimeKnown = false,
            durationKnown = true,
        )
        val sets = listOf(setHistory(original, order = 0u), setHistory(original, order = 1u))
        database.workoutHistoryDao().insert(original)
        sets.forEach { database.setHistoryDao().insert(it) }

        val corrected = WorkoutHistoryDateCorrectionService.correctImportedDate(
            database = database,
            profileId = profileId,
            activeProfileId = activeProfileId,
            historyId = original.id,
            correctedDate = correctedDate,
        )

        val expected = original.copy(
            date = correctedDate,
            time = LocalTime.MIDNIGHT,
            startTime = LocalDateTime.of(correctedDate, LocalTime.MIDNIGHT),
        )
        assertEquals(expected, corrected)
        assertEquals(expected, database.workoutHistoryDao().getWorkoutHistoryById(original.id))
        val savedSets = database.setHistoryDao().getSetHistoriesByWorkoutHistoryId(original.id)
        assertEquals(sets.associateBy { it.id }, savedSets.associateBy { it.id })
        assertEquals(2, savedSets.size)
    }

    @Test
    fun rejectsWrongProfileRecordedAndKnownStartTimeWithoutChangingRows() = runBlocking {
        val eligible = history(historyId, WorkoutHistoryOrigin.USER_IMPORTED, startTimeKnown = false)
        val recorded = history(UUID.randomUUID(), WorkoutHistoryOrigin.RECORDED, startTimeKnown = false)
        val knownStart = history(UUID.randomUUID(), WorkoutHistoryOrigin.USER_IMPORTED, startTimeKnown = true)
        listOf(eligible, recorded, knownStart).forEach { database.workoutHistoryDao().insert(it) }

        assertIllegalArgument {
            WorkoutHistoryDateCorrectionService.correctImportedDate(
                database, profileId, "another-profile", eligible.id, correctedDate,
            )
        }
        for (notEditable in listOf(recorded, knownStart)) {
            assertIllegalArgument {
                WorkoutHistoryDateCorrectionService.correctImportedDate(
                    database, profileId, activeProfileId, notEditable.id, correctedDate,
                )
            }
        }
        listOf(eligible, recorded, knownStart).forEach { expected ->
            assertEquals(expected, database.workoutHistoryDao().getWorkoutHistoryById(expected.id))
        }
    }

    private fun history(
        id: UUID,
        origin: WorkoutHistoryOrigin,
        startTimeKnown: Boolean,
        durationKnown: Boolean = false,
    ) = WorkoutHistory(
        id = id,
        workoutId = UUID.randomUUID(),
        date = originalDate,
        time = LocalTime.MIDNIGHT,
        startTime = LocalDateTime.of(originalDate, LocalTime.MIDNIGHT),
        duration = if (durationKnown) 5_400 else 0,
        heartBeatRecords = emptyList(),
        isDone = true,
        hasBeenSentToHealth = false,
        globalId = UUID.randomUUID(),
        recurringSessionId = UUID.randomUUID(),
        origin = origin,
        startTimeKnown = startTimeKnown,
        durationKnown = durationKnown,
    )

    private fun setHistory(history: WorkoutHistory, order: UInt) = SetHistory(
        id = UUID.randomUUID(),
        workoutHistoryId = history.id,
        exerciseId = UUID.randomUUID(),
        setId = UUID.randomUUID(),
        order = order,
        startTime = null,
        endTime = null,
        setData = WeightSetData(actualReps = 8, actualWeight = 37.5 + order.toDouble(), volume = 300.0),
        skipped = false,
        recurringExerciseId = UUID.randomUUID(),
        exerciseDefinitionIdSnapshot = UUID.randomUUID(),
        exerciseTypeSnapshot = "WEIGHT",
        exerciseNameSnapshot = "Recorded performance",
    )

    private suspend fun assertIllegalArgument(block: suspend () -> Unit) {
        val failure = runCatching { block() }.exceptionOrNull()
        assertTrue("Expected IllegalArgumentException, got $failure", failure is IllegalArgumentException)
    }
}
