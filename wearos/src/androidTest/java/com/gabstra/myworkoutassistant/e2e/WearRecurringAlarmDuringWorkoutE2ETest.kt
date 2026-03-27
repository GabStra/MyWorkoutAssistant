package com.gabstra.myworkoutassistant.e2e

import android.Manifest
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.helpers.WearAlarmTriggerHelper
import com.gabstra.myworkoutassistant.e2e.fixtures.AlarmTriggerWorkoutStoreFixture
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import java.time.Duration
import java.time.LocalDateTime
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearRecurringAlarmDuringWorkoutE2ETest : WearBaseE2ETest() {
    private lateinit var recurringAlarmExpectation: WearAlarmTriggerHelper.RecurringAlarmExpectation

    override fun prepareAppStateBeforeLaunch() {
        grantPermissions(Manifest.permission.POST_NOTIFICATIONS)
        WearAlarmTriggerHelper.ensureExactAlarmAccess(device, context)
        WearAlarmTriggerHelper.clearAlarmNotifications(context)
        AlarmTriggerWorkoutStoreFixture.setupWorkoutStore(context)

        recurringAlarmExpectation = WearAlarmTriggerHelper.createLocalRecurringAlarmExpectation()
        runBlocking {
            WearAlarmTriggerHelper.replaceSchedules(context, listOf(recurringAlarmExpectation.schedule))
        }
        WorkoutAlarmScheduler(context).scheduleWorkout(recurringAlarmExpectation.schedule)
    }

    @Test
    fun recurringAlarmWhileWorkoutInProgress_isSuppressedAndRescheduled() {
        runBlocking {
            WearAlarmTriggerHelper.ensurePostNotificationsGranted(context)

            WearAlarmTriggerHelper.waitForNextAlarmClockTrigger(
                context = context,
                expectedTriggerAt = recurringAlarmExpectation.triggerAt,
                timeoutMs = 10_000
            )

            WearAlarmTriggerHelper.setWorkoutInProgress(context, true)
            try {
                val quietWindowMs =
                    Duration.between(LocalDateTime.now(), recurringAlarmExpectation.triggerAt)
                        .toMillis()
                        .coerceAtLeast(0L) + 20_000L

                WearAlarmTriggerHelper.assertAlarmUiDoesNotAppear(timeoutMs = quietWindowMs)

                WearAlarmTriggerHelper.waitForRecurringScheduleAdvanced(
                    context = context,
                    scheduleId = recurringAlarmExpectation.schedule.id,
                    expectedNotificationDate = recurringAlarmExpectation.triggerAt.toLocalDate(),
                    timeoutMs = 15_000
                )

                WearAlarmTriggerHelper.waitForNextAlarmClockTrigger(
                    context = context,
                    expectedTriggerAt = recurringAlarmExpectation.nextTriggerAt,
                    timeoutMs = 15_000
                )
            } finally {
                WearAlarmTriggerHelper.setWorkoutInProgress(context, false)
            }
        }
    }
}
