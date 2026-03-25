package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutRecordDaoOrphanTest {

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
    fun deleteOrphanedRecords_removesRowsWithoutHistory() = runBlocking {
        val workoutId = UUID.randomUUID()
        val missingHistoryId = UUID.randomUUID()
        db.workoutRecordDao().insert(
            WorkoutRecord(
                id = UUID.randomUUID(),
                workoutId = workoutId,
                workoutHistoryId = missingHistoryId,
                setIndex = 0u,
                exerciseId = UUID.randomUUID(),
            )
        )
        assertEquals(1, db.workoutRecordDao().getAll().size)
        db.workoutRecordDao().deleteOrphanedRecords()
        assertTrue(db.workoutRecordDao().getAll().isEmpty())
    }
}
