package com.gabstra.myworkoutassistant.receivers

import android.app.AlarmManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler

class AlarmPermissionChangeReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == AlarmManager.ACTION_SCHEDULE_EXACT_ALARM_PERMISSION_STATE_CHANGED) {

            val alarmManager = context.getSystemService(Context.ALARM_SERVICE) as AlarmManager

            if(alarmManager.canScheduleExactAlarms()){
                val scheduler = WorkoutAlarmScheduler(context)
                scheduler.rescheduleAllWorkouts()
            }
        }
    }
}