package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime
import java.util.UUID
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class WorkoutSyncVerificationTest {

    @Test
    fun crossDeviceSync_wearWorkoutHistoryArrivesOnPhone() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        val deadline = System.currentTimeMillis() + 120_000
        var exactMatchFound = false

        while (System.currentTimeMillis() < deadline) {
            val doneHistories = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(true)
            exactMatchFound = doneHistories.any { workoutHistory ->
                val ageMinutes = Duration.between(workoutHistory.startTime, LocalDateTime.now()).toMinutes()
                if (ageMinutes < 0 || ageMinutes > 120) {
                    return@any false
                }

                if (workoutHistory.workoutId != CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID ||
                    workoutHistory.globalId != CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID ||
                    !workoutHistory.isDone
                ) {
                    return@any false
                }

                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                if (setHistories.size != expectedSetSpecs.size) {
                    return@any false
                }

                val actualBySetId = setHistories.associateBy { it.setId }
                if (actualBySetId.keys != expectedSetSpecs.keys) {
                    return@any false
                }

                expectedSetSpecs.all { (setId, spec) ->
                    val setHistory = actualBySetId[setId] ?: return@all false
                    val weightData = setHistory.setData as? WeightSetData ?: return@all false
                    !setHistory.skipped &&
                        setHistory.exerciseId == spec.exerciseId &&
                        setHistory.order.toInt() == spec.order &&
                        weightData.actualReps == spec.expectedReps &&
                        abs(weightData.actualWeight - spec.expectedWeight) <= CrossDeviceSyncPhoneWorkoutStoreFixture.WEIGHT_TOLERANCE
                }
            }

            if (exactMatchFound) {
                break
            }

            delay(2_000)
        }

        require(exactMatchFound) {
            "Exact synced workout history match not found on mobile within timeout. " +
                "Expected workoutId=${CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_ID}, " +
                "globalId=${CrossDeviceSyncPhoneWorkoutStoreFixture.WORKOUT_GLOBAL_ID}, " +
                "set IDs=${expectedSetSpecs.keys} with exact exercise/order/reps/weight values."
        }
    }

    companion object {
        private data class ExpectedSetSpec(
            val exerciseId: UUID,
            val order: Int,
            val expectedReps: Int,
            val expectedWeight: Double
        )

        private val expectedSetSpecs: Map<UUID, ExpectedSetSpec> = mapOf(
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_ID to ExpectedSetSpec(
                exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_A_ID,
                order = 0,
                expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_EXPECTED_REPS,
                expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A1_EXPECTED_WEIGHT
            ),
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_ID to ExpectedSetSpec(
                exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_A_ID,
                order = 1,
                expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_EXPECTED_REPS,
                expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_A2_EXPECTED_WEIGHT
            ),
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_ID to ExpectedSetSpec(
                exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_B_ID,
                order = 0,
                expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_EXPECTED_REPS,
                expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_B1_EXPECTED_WEIGHT
            ),
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_ID to ExpectedSetSpec(
                exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_C_ID,
                order = 0,
                expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_EXPECTED_REPS,
                expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_C1_EXPECTED_WEIGHT
            ),
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_ID to ExpectedSetSpec(
                exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_D_ID,
                order = 0,
                expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_EXPECTED_REPS,
                expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D1_EXPECTED_WEIGHT
            ),
            CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_ID to ExpectedSetSpec(
                exerciseId = CrossDeviceSyncPhoneWorkoutStoreFixture.EXERCISE_D_ID,
                order = 1,
                expectedReps = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_EXPECTED_REPS,
                expectedWeight = CrossDeviceSyncPhoneWorkoutStoreFixture.SET_D2_EXPECTED_WEIGHT
            )
        )
    }
}
