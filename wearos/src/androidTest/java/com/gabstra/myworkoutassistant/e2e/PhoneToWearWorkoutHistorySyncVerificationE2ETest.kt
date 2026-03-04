package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import java.time.Duration
import java.time.LocalDateTime
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class PhoneToWearWorkoutHistorySyncVerificationE2ETest {

    @Test
    fun phoneSync_sendsWorkoutHistoryToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val workoutHistoryDao = db.workoutHistoryDao()
        val setHistoryDao = db.setHistoryDao()

        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS
        var exactMatchFound = false

        while (System.currentTimeMillis() < deadline) {
            val doneHistories = workoutHistoryDao.getAllWorkoutHistoriesByIsDone(true)
            exactMatchFound = doneHistories.any { workoutHistory ->
                val ageMinutes = Duration.between(workoutHistory.startTime, LocalDateTime.now()).toMinutes()
                if (ageMinutes < 0 || ageMinutes > 180) {
                    return@any false
                }

                if (
                    workoutHistory.workoutId != CrossDeviceSyncWorkoutStoreFixture.WORKOUT_ID ||
                    workoutHistory.globalId != CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_GLOBAL_ID ||
                    workoutHistory.id != CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID
                ) {
                    return@any false
                }

                val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryId(workoutHistory.id)
                val setA1 = setHistories.firstOrNull { it.setId == CrossDeviceSyncWorkoutStoreFixture.SET_A1_ID }
                    ?: return@any false
                val setA2 = setHistories.firstOrNull { it.setId == CrossDeviceSyncWorkoutStoreFixture.SET_A2_ID }
                    ?: return@any false

                val setA1Data = setA1.setData as? WeightSetData ?: return@any false
                val setA2Data = setA2.setData as? WeightSetData ?: return@any false

                !setA1.skipped &&
                    !setA2.skipped &&
                    setA1.exerciseId == CrossDeviceSyncWorkoutStoreFixture.EXERCISE_A_ID &&
                    setA2.exerciseId == CrossDeviceSyncWorkoutStoreFixture.EXERCISE_A_ID &&
                    setA1.order.toInt() == 0 &&
                    setA2.order.toInt() == 1 &&
                    setA1Data.actualReps == CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A1_REPS &&
                    setA2Data.actualReps == CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A2_REPS &&
                    abs(
                        setA1Data.actualWeight - CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A1_WEIGHT
                    ) <= CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_WEIGHT_TOLERANCE &&
                    abs(
                        setA2Data.actualWeight - CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_A2_WEIGHT
                    ) <= CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_WEIGHT_TOLERANCE
            }

            if (exactMatchFound) {
                break
            }
            delay(500)
        }

        require(exactMatchFound) {
            "Expected phone->wear synced workout history not found on Wear within timeout. " +
                "Expected historyId=${CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID}, " +
                "globalId=${CrossDeviceSyncWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_GLOBAL_ID} " +
                "with deterministic set payload values for A1/A2."
        }
    }
}
