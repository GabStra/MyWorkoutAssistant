package com.gabstra.myworkoutassistant.e2e.helpers

import android.Manifest
import android.app.AlarmManager
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import androidx.test.uiautomator.By
import androidx.test.uiautomator.UiDevice
import com.gabstra.myworkoutassistant.WorkoutAlarmActivity
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import com.gabstra.myworkoutassistant.e2e.fixtures.AlarmTriggerWorkoutStoreFixture
import com.gabstra.myworkoutassistant.notifications.WorkoutNotificationHelper
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import java.time.Duration
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.UUID
import kotlinx.coroutines.delay

object WearAlarmTriggerHelper {
    private const val EXACT_ALARM_APP_OP = "SCHEDULE_EXACT_ALARM"
    private const val APP_OP_ALLOW = "allow"
    private const val LOCAL_TRIGGER_MIN_LEAD_SECONDS = 20L
    private const val CROSS_DEVICE_TRIGGER_MIN_LEAD_SECONDS = 180L

    data class AlarmExpectation(
        val schedule: WorkoutSchedule,
        val triggerAt: LocalDateTime
    )

    data class RecurringAlarmExpectation(
        val schedule: WorkoutSchedule,
        val triggerAt: LocalDateTime,
        val nextTriggerAt: LocalDateTime
    )

    fun createLocalAlarmExpectation(
        now: LocalDateTime = LocalDateTime.now()
    ): AlarmExpectation = createAlarmExpectation(
        scheduleFactory = AlarmTriggerWorkoutStoreFixture::createSchedule,
        minLeadSeconds = LOCAL_TRIGGER_MIN_LEAD_SECONDS,
        now = now
    )

    fun createCrossDeviceAlarmExpectation(
        scheduleFactory: (LocalDateTime) -> WorkoutSchedule,
        now: LocalDateTime = LocalDateTime.now()
    ): AlarmExpectation = createAlarmExpectation(
        scheduleFactory = scheduleFactory,
        minLeadSeconds = CROSS_DEVICE_TRIGGER_MIN_LEAD_SECONDS,
        now = now
    )

    fun createLocalRecurringAlarmExpectation(
        now: LocalDateTime = LocalDateTime.now()
    ): RecurringAlarmExpectation {
        val triggerAt = nextMinuteBoundaryAfter(now, LOCAL_TRIGGER_MIN_LEAD_SECONDS)
        val recurringDays =
            dayBitFor(triggerAt.toLocalDate()) or dayBitFor(triggerAt.toLocalDate().plusDays(1))
        return RecurringAlarmExpectation(
            schedule = AlarmTriggerWorkoutStoreFixture.createRecurringSchedule(triggerAt, recurringDays),
            triggerAt = triggerAt,
            nextTriggerAt = triggerAt.plusDays(1)
        )
    }

    fun ensurePostNotificationsGranted(context: Context) {
        require(
            ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        ) {
            "POST_NOTIFICATIONS permission was not granted before alarm verification."
        }
    }

    fun ensureExactAlarmAccess(device: UiDevice, context: Context, timeoutMs: Long = 10_000) {
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        if (alarmManager.canScheduleExactAlarms()) {
            return
        }

        runCatching {
            device.executeShellCommand(
                "appops set ${context.packageName} $EXACT_ALARM_APP_OP $APP_OP_ALLOW"
            )
        }
        waitForExactAlarmAccess(context, timeoutMs)
    }

    suspend fun replaceSchedules(context: Context, schedules: List<WorkoutSchedule>) {
        val db = AppDatabase.getDatabase(context)
        db.workoutScheduleDao().deleteAll()
        if (schedules.isNotEmpty()) {
            db.workoutScheduleDao().insertAll(*schedules.toTypedArray())
        }
    }

    fun clearAlarmNotifications(context: Context) {
        runCatching {
            val notificationManager =
                context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.cancelAll()
            WorkoutNotificationHelper(context).clearChannelNotifications()
        }
    }

    fun setWorkoutInProgress(context: Context, isInProgress: Boolean) {
        context.getSharedPreferences("workout_state", Context.MODE_PRIVATE)
            .edit()
            .putBoolean("isWorkoutInProgress", isInProgress)
            .commit()
    }

    suspend fun waitForSchedulePreTriggerState(
        context: Context,
        scheduleId: UUID,
        earliestTriggerAt: LocalDateTime,
        timeoutMs: Long
    ): WorkoutSchedule {
        val db = AppDatabase.getDatabase(context)
        val dao = db.workoutScheduleDao()
        val deadline = System.currentTimeMillis() + timeoutMs

        while (System.currentTimeMillis() < deadline) {
            val schedule = dao.getScheduleById(scheduleId)
            if (schedule != null &&
                !schedule.hasExecuted &&
                schedule.lastNotificationSentAt == null &&
                schedule.specificDate != null &&
                schedule.triggerAtOrNull()?.isAfter(earliestTriggerAt) == true
            ) {
                return schedule
            }
            delay(500)
        }

        val finalSchedule = dao.getScheduleById(scheduleId)
        error(
            "Schedule $scheduleId did not reach a fresh pre-trigger state within ${timeoutMs}ms. " +
                "Observed=$finalSchedule earliestTriggerAt=$earliestTriggerAt"
        )
    }

    suspend fun waitForAlarmUi(
        device: UiDevice,
        expectedTitle: String,
        expectedMessage: String,
        timeoutMs: Long
    ) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            val resumedAlarmActivity = resumedAlarmActivityOrNull()
            val titleVisible = device.hasObject(By.text(expectedTitle))
            val messageVisible = device.hasObject(By.text(expectedMessage))

            if (resumedAlarmActivity != null && (titleVisible || messageVisible)) {
                return
            }

            delay(250)
        }

        error(
            "WorkoutAlarmActivity did not become visible within ${timeoutMs}ms " +
                "for title='$expectedTitle' message='$expectedMessage'."
        )
    }

    suspend fun waitForTriggeredOneTimeSchedule(
        context: Context,
        scheduleId: UUID,
        timeoutMs: Long
    ): WorkoutSchedule {
        val db = AppDatabase.getDatabase(context)
        val dao = db.workoutScheduleDao()
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val schedule = dao.getScheduleById(scheduleId)
            if (schedule != null &&
                schedule.hasExecuted &&
                schedule.lastNotificationSentAt == LocalDate.now()
            ) {
                return schedule
            }
            delay(500)
        }

        error(
            "One-time schedule $scheduleId was not marked executed with today's notification date " +
                "within ${timeoutMs}ms."
        )
    }

    suspend fun waitForRecurringScheduleAdvanced(
        context: Context,
        scheduleId: UUID,
        expectedNotificationDate: LocalDate,
        timeoutMs: Long
    ): WorkoutSchedule {
        val db = AppDatabase.getDatabase(context)
        val dao = db.workoutScheduleDao()
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val schedule = dao.getScheduleById(scheduleId)
            if (schedule != null &&
                !schedule.hasExecuted &&
                schedule.lastNotificationSentAt == expectedNotificationDate &&
                schedule.daysOfWeek > 0 &&
                schedule.specificDate == null
            ) {
                return schedule
            }
            delay(500)
        }

        error(
            "Recurring schedule $scheduleId was not advanced with notification date " +
                "$expectedNotificationDate within ${timeoutMs}ms."
        )
    }

    suspend fun assertAlarmUiDoesNotAppear(timeoutMs: Long) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (resumedAlarmActivityOrNull() != null) {
                error("WorkoutAlarmActivity became visible while workout-in-progress suppression was expected.")
            }
            delay(250)
        }
    }

    suspend fun waitForNextAlarmClockTrigger(
        context: Context,
        expectedTriggerAt: LocalDateTime,
        timeoutMs: Long,
        toleranceMs: Long = 60_000
    ): Long {
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val expectedTriggerMs =
            expectedTriggerAt.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()
        val deadline = System.currentTimeMillis() + timeoutMs

        while (System.currentTimeMillis() < deadline) {
            val nextAlarmClock = alarmManager.nextAlarmClock
            val triggerTime = nextAlarmClock?.triggerTime
            if (triggerTime != null && kotlin.math.abs(triggerTime - expectedTriggerMs) <= toleranceMs) {
                return triggerTime
            }
            delay(500)
        }

        error(
            "AlarmManager.nextAlarmClock did not advance to $expectedTriggerAt " +
                "within ${timeoutMs}ms."
        )
    }

    private fun createAlarmExpectation(
        scheduleFactory: (LocalDateTime) -> WorkoutSchedule,
        minLeadSeconds: Long,
        now: LocalDateTime
    ): AlarmExpectation {
        val triggerAt = nextMinuteBoundaryAfter(now, minLeadSeconds)
        return AlarmExpectation(
            schedule = scheduleFactory(triggerAt),
            triggerAt = triggerAt
        )
    }

    private fun nextMinuteBoundaryAfter(now: LocalDateTime, minLeadSeconds: Long): LocalDateTime {
        var candidate = now.withSecond(0).withNano(0).plusMinutes(1)
        while (Duration.between(now, candidate).seconds < minLeadSeconds) {
            candidate = candidate.plusMinutes(1)
        }
        return candidate
    }

    private fun dayBitFor(date: LocalDate): Int {
        val zeroBasedDayOfWeek = date.dayOfWeek.value % 7
        return 1 shl zeroBasedDayOfWeek
    }

    private fun waitForExactAlarmAccess(context: Context, timeoutMs: Long) {
        val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (alarmManager.canScheduleExactAlarms()) {
                return
            }
            Thread.sleep(E2ETestTimings.SHORT_IDLE_MS)
        }
        error("Exact alarm access was not granted within ${timeoutMs}ms.")
    }

    private fun resumedAlarmActivityOrNull(): WorkoutAlarmActivity? {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        var activity: WorkoutAlarmActivity? = null
        instrumentation.runOnMainSync {
            activity = ActivityLifecycleMonitorRegistry.getInstance()
                .getActivitiesInStage(Stage.RESUMED)
                .firstOrNull { it is WorkoutAlarmActivity } as? WorkoutAlarmActivity
        }
        return activity
    }

    private fun WorkoutSchedule.triggerAtOrNull(): LocalDateTime? {
        val date = specificDate ?: return null
        return date.atTime(hour, minute)
    }
}
