package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.helpers.CrossDeviceSyncTestPrerequisites
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
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
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class TuesdayWorkoutSyncVerificationTest {
    @Test
    fun completedTuesdayWorkoutIsStoredEndToEndOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val historyId = CrossDeviceSyncTestPrerequisites.findRecentMatchingHistoryId(
            context = context,
            timeoutMs = 90_000
        ) { db, history ->
            history.isDone &&
                history.workoutId == WORKOUT_ID &&
                db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(history.id).size == EXPECTED_SET_COUNT
        } ?: error("Completed Tuesday workout history did not arrive on the phone.")

        val db = AppDatabase.getDatabase(context)
        val setHistories = db.setHistoryDao().getSetHistoriesByWorkoutHistoryIdOrdered(historyId)
        val setCountsByExercise = setHistories.groupingBy { it.exerciseId }.eachCount()
        assertEquals(EXPECTED_SET_COUNT, setHistories.size)
        assertEquals(EXPECTED_FIXED_SET_COUNTS_BY_EXERCISE, setCountsByExercise.filterKeys {
            it in EXPECTED_FIXED_SET_COUNTS_BY_EXERCISE
        })
        assertTrue((setCountsByExercise[SEATED_PRESS_ID] ?: 0) >= 3)
        assertTrue((setCountsByExercise[BARBELL_ROW_ID] ?: 0) >= 3)
        assertEquals(11, (setCountsByExercise[SEATED_PRESS_ID] ?: 0) + (setCountsByExercise[BARBELL_ROW_ID] ?: 0))
        assertEquals(
            5,
            setHistories.count {
                when (val setData = it.setData) {
                    is WeightSetData -> setData.subCategory == SetSubCategory.WarmupSet
                    is BodyWeightSetData -> setData.subCategory == SetSubCategory.WarmupSet
                    else -> false
                }
            }
        )
        assertEquals(
            2,
            setHistories.count {
                (it.setData as? WeightSetData)?.subCategory == SetSubCategory.CalibrationSet
            }
        )
        assertNull(db.workoutRecordDao().getWorkoutRecordByWorkoutId(WORKOUT_ID))
        assertFalse(db.workoutHistoryDao().getAllWorkoutHistories().any {
            it.workoutId == WORKOUT_ID && !it.isDone
        })

        val workout = WorkoutStoreRepository(context.filesDir).getWorkoutStore().workouts.single {
            it.id == WORKOUT_ID
        }
        val calibrationSuperset = workout.workoutComponents.last() as Superset
        assertTrue(calibrationSuperset.exercises.all { !it.requiresLoadCalibration })
        assertEquals(setOf(SHRUG_ID, FACE_PULL_ID), calibrationSuperset.exercises.map { it.id }.toSet())
    }

    companion object {
        private val WORKOUT_ID = UUID.fromString("4b3a063e-29ef-45e1-99fb-aa38a396c772")
        private const val EXPECTED_SET_COUNT = 22
        private val SEATED_PRESS_ID = UUID.fromString("215cad3c-20a4-4a2c-b41d-ec96760aba8b")
        private val BARBELL_ROW_ID = UUID.fromString("f4811d77-9ab6-47c3-9f0f-cb777e278428")
        private val SHRUG_ID = UUID.fromString("9178a84e-6d74-49af-8571-fa731912a38b")
        private val FACE_PULL_ID = UUID.fromString("0809fddd-765f-4c79-a907-3ad4e09dd402")
        private val EXPECTED_FIXED_SET_COUNTS_BY_EXERCISE = mapOf(
            UUID.fromString("c3813f52-7e02-4dee-9094-3288f8e33edb") to 1,
            UUID.fromString("56d72702-274f-4a3f-a7b4-c3108c2f1d47") to 2,
            UUID.fromString("4498927f-4d56-4388-84aa-77d51b861383") to 2,
            SHRUG_ID to 3,
            FACE_PULL_ID to 3
        )
    }
}
