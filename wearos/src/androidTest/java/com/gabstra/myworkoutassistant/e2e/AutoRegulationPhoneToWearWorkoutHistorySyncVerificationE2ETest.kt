package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.AutoRegulationSetBadgeWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.abs

@RunWith(AndroidJUnit4::class)
class AutoRegulationPhoneToWearWorkoutHistorySyncVerificationE2ETest {
    @Test
    fun phoneSync_sendsAutoRegulationHistoryToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val db = AppDatabase.getDatabase(context)
        val deadline = System.currentTimeMillis() + E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS

        while (System.currentTimeMillis() < deadline) {
            val history = db.workoutHistoryDao().getWorkoutHistoryById(
                AutoRegulationSetBadgeWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID
            )
            if (history != null) {
                val set1 = db.setHistoryDao().getSetHistoryByWorkoutHistoryIdAndSetId(
                    AutoRegulationSetBadgeWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID,
                    AutoRegulationSetBadgeWorkoutStoreFixture.SET_1_ID
                )?.setData as? WeightSetData
                val set2 = db.setHistoryDao().getSetHistoryByWorkoutHistoryIdAndSetId(
                    AutoRegulationSetBadgeWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID,
                    AutoRegulationSetBadgeWorkoutStoreFixture.SET_2_ID
                )?.setData as? WeightSetData

                require(set1 != null && set2 != null) {
                    "Phone-seeded auto-regulation set histories were not found on Wear."
                }
                require(set1.actualReps == AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_REPS) {
                    "Synced first-set reps mismatch. expected=${AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_REPS} actual=${set1.actualReps}"
                }
                require(set2.actualReps == AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_REPS) {
                    "Synced second-set reps mismatch. expected=${AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_REPS} actual=${set2.actualReps}"
                }
                require(
                    abs(set1.actualWeight - AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT) <=
                        AutoRegulationSetBadgeWorkoutStoreFixture.WEIGHT_TOLERANCE
                ) {
                    "Synced first-set weight mismatch. expected=${AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT} actual=${set1.actualWeight}"
                }
                require(
                    abs(set2.actualWeight - AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT) <=
                        AutoRegulationSetBadgeWorkoutStoreFixture.WEIGHT_TOLERANCE
                ) {
                    "Synced second-set weight mismatch. expected=${AutoRegulationSetBadgeWorkoutStoreFixture.TEMPLATE_WEIGHT} actual=${set2.actualWeight}"
                }
                return@runBlocking
            }
            delay(500)
        }

        error(
            "Expected phone->wear auto-regulation history not found on Wear within timeout. " +
                "historyId=${AutoRegulationSetBadgeWorkoutStoreFixture.PHONE_TO_WEAR_HISTORY_ID}"
        )
    }
}
