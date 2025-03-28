package com.gabstra.myworkoutassistant.receivers

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.annotation.RequiresApi
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            val scheduler = WorkoutAlarmScheduler(context)
            scheduler.rescheduleAllWorkouts()
        }
    }
}
