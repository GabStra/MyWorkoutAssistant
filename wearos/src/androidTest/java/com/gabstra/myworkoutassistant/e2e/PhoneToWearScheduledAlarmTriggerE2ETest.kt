package com.gabstra.myworkoutassistant.e2e

import android.Manifest
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.e2e.fixtures.AlarmTriggerWorkoutStoreFixture
import com.gabstra.myworkoutassistant.e2e.helpers.WearAlarmTriggerHelper
import java.time.Duration
import java.time.LocalDateTime
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneToWearScheduledAlarmTriggerE2ETest : WearBaseE2ETest() {
    override fun prepareAppStateBeforeLaunch() {
        grantPermissions(Manifest.permission.POST_NOTIFICATIONS)
        WearAlarmTriggerHelper.ensureExactAlarmAccess(device, context)
        WearAlarmTriggerHelper.clearAlarmNotifications(context)
    }

    @Test
    fun syncedPhoneSchedule_triggersWearAlarmUi() {
        runBlocking {
            WearAlarmTriggerHelper.ensurePostNotificationsGranted(context)

            val testStart = LocalDateTime.now()
            val schedule = WearAlarmTriggerHelper.waitForSchedulePreTriggerState(
                context = context,
                scheduleId = AlarmTriggerWorkoutStoreFixture.SCHEDULE_ID,
                earliestTriggerAt = testStart.plusSeconds(30),
                timeoutMs = E2ETestTimings.CROSS_DEVICE_SYNC_TIMEOUT_MS
            )

            val triggerAt = schedule.specificDate!!.atTime(schedule.hour, schedule.minute)
            val triggerTimeoutMs =
                Duration.between(LocalDateTime.now(), triggerAt)
                    .toMillis()
                    .coerceAtLeast(0L) + 90_000L

            WearAlarmTriggerHelper.waitForAlarmUi(
                device = device,
                expectedTitle = AlarmTriggerWorkoutStoreFixture.WORKOUT_NAME,
                expectedMessage = schedule.label,
                timeoutMs = triggerTimeoutMs
            )

            WearAlarmTriggerHelper.waitForTriggeredOneTimeSchedule(
                context = context,
                scheduleId = schedule.id,
                timeoutMs = 15_000
            )
        }
    }
}
