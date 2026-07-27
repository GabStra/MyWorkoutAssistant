package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class CalibrationSupersetWorkoutSyncVerificationTest {
    @Test
    fun crossDeviceSync_completedCalibrationSupersetIsStoredCorrectlyOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val historyId = CrossDeviceSyncTestPrerequisites.findRecentMatchingHistoryId(
            context = context,
            timeoutMs = 60_000
        ) { db, history ->
            history.isDone &&
                history.workoutId == CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID &&
                history.globalId == CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID &&
                db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id).size == 4
        } ?: error("Completed calibration superset history did not arrive on the phone.")

        val db = AppDatabase.getDatabase(context)
        val histories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(historyId)
        assertEquals(4, histories.size)
        assertEquals(
            setOf(
                CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.EXERCISE_A_ID,
                CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.EXERCISE_B_ID
            ),
            histories.map { it.exerciseId }.toSet()
        )
        assertEquals(
            mapOf(
                CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.EXERCISE_A_ID to 2,
                CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.EXERCISE_B_ID to 2
            ),
            histories.groupingBy { it.exerciseId }.eachCount()
        )
        assertTrue(histories.all { it.setData is WeightSetData })
        assertEquals(2, histories.count { (it.setData as WeightSetData).subCategory == SetSubCategory.CalibrationSet })
        assertEquals(2, histories.count { (it.setData as WeightSetData).subCategory == SetSubCategory.WorkSet })
        assertNull(
            db.workoutRecordDao().getWorkoutRecordByWorkoutId(
                CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID
            )
        )
        assertFalse(
            db.workoutHistoryDao().getAllWorkoutHistories().any {
                !it.isDone &&
                    it.workoutId == CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID
            }
        )

        val workout = WorkoutStoreRepository(context.filesDir).getWorkoutStore().workouts.single {
            it.id == CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.WORKOUT_ID
        }
        val superset = workout.workoutComponents.single() as Superset
        assertTrue(superset.exercises.all { !it.requiresLoadCalibration })
        assertEquals(
            setOf(
                CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.WORK_SET_A_ID,
                CalibrationSupersetCrossDevicePhoneWorkoutStoreFixture.WORK_SET_B_ID
            ),
            superset.exercises.flatMap { it.sets }.map { it.id }.toSet()
        )
    }
}
