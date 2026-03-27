package com.gabstra.myworkoutassistant.receivers

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        when (intent.action) {
            Intent.ACTION_BOOT_COMPLETED,
            Intent.ACTION_DATE_CHANGED,
            Intent.ACTION_MY_PACKAGE_REPLACED,
            Intent.ACTION_TIMEZONE_CHANGED,
            Intent.ACTION_TIME_CHANGED -> {
                val scheduler = WorkoutAlarmScheduler(context)
                scheduler.rescheduleAllWorkouts()
            }
        }
    }
}
