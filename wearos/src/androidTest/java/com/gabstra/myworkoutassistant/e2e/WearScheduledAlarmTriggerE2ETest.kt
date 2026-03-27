package com.gabstra.myworkoutassistant.e2e

import android.Manifest
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.AlarmTriggerWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearAlarmTriggerHelper
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import java.time.Duration
import java.time.LocalDateTime
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WearScheduledAlarmTriggerE2ETest : WearBaseE2ETest() {
    private lateinit var alarmExpectation: WearAlarmTriggerHelper.AlarmExpectation

    override fun prepareAppStateBeforeLaunch() {
        grantPermissions(Manifest.permission.POST_NOTIFICATIONS)
        WearAlarmTriggerHelper.ensureExactAlarmAccess(device, context)
        WearAlarmTriggerHelper.clearAlarmNotifications(context)
        AlarmTriggerWorkoutStoreFixture.setupWorkoutStore(context)

        alarmExpectation = WearAlarmTriggerHelper.createLocalAlarmExpectation()
        runBlocking {
            WearAlarmTriggerHelper.replaceSchedules(context, listOf(alarmExpectation.schedule))
        }
        WorkoutAlarmScheduler(context).scheduleWorkout(alarmExpectation.schedule)
    }

    @Test
    fun scheduledAlarmAlreadyOnWear_triggersAlarmUi() {
        runBlocking {
            WearAlarmTriggerHelper.ensurePostNotificationsGranted(context)

            WearAlarmTriggerHelper.waitForSchedulePreTriggerState(
                context = context,
                scheduleId = alarmExpectation.schedule.id,
                earliestTriggerAt = alarmExpectation.triggerAt.minusSeconds(1),
                timeoutMs = 10_000
            )

            val triggerTimeoutMs =
                Duration.between(LocalDateTime.now(), alarmExpectation.triggerAt)
                    .toMillis()
                    .coerceAtLeast(0L) + 90_000L

            WearAlarmTriggerHelper.waitForAlarmUi(
                device = device,
                expectedTitle = AlarmTriggerWorkoutStoreFixture.WORKOUT_NAME,
                expectedMessage = AlarmTriggerWorkoutStoreFixture.SCHEDULE_LABEL,
                timeoutMs = triggerTimeoutMs
            )

            WearAlarmTriggerHelper.waitForTriggeredOneTimeSchedule(
                context = context,
                scheduleId = alarmExpectation.schedule.id,
                timeoutMs = 15_000
            )
        }
    }
}
