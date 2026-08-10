package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncAssertions
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Phone verifier for prescription identity and set identity after Wear delivery. */
@RunWith(AndroidJUnit4::class)
class ExerciseLibraryPrescriptionCrossDeviceVerificationTest {
    @Test
    fun schemaV2PrescriptionHistory_preservesPrescriptionAndSetIds() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        CrossDeviceSyncAssertions.waitForCheckpoint(
            context = context,
            checkpoint = CrossDeviceSyncAssertions.finalCheckpoint,
            timeoutMs = 45_000,
        )
        val db = AppDatabase.getDatabase(context)
        val history = db.workoutHistoryDao().getAllWorkoutHistories().first {
            it.isDone && it.workoutId == CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID
        }
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryId(history.id)
        assertEquals(
            CrossDeviceSyncAssertions.finalCheckpoint.expectedSetIds.toSet(),
            setHistories.map { it.setId }.toSet(),
        )
        assertTrue(setHistories.all { it.exerciseId in setOf(
            CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_A_ID,
            CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_B_ID,
            CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_C_ID,
            CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_D_ID,
        ) })
    }
}
