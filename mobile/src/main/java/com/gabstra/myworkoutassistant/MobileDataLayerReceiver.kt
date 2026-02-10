package com.gabstra.myworkoutassistant

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import androidx.health.connect.client.HealthConnectClient
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.migrateWorkoutStoreSetIdsIfNeeded
import com.gabstra.myworkoutassistant.shared.viewmodels.WorkoutViewModel
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.Calendar

internal class MobileDataLayerReceiver(
    private val appViewModel: AppViewModel,
    private val workoutViewModel: WorkoutViewModel,
    private val workoutStoreRepository: WorkoutStoreRepository,
    private val activity: Activity
) : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        activity.run {
            try {
                handleWorkoutUpdatesIfPresent(intent)
                showErrorLogsSyncedToastIfPresent(context, intent)
            } catch (exception: Exception) {
                Log.e("MyWorkoutAssistant", "Error in MobileDataLayerReceiver", exception)
            }
        }
    }

    private fun handleWorkoutUpdatesIfPresent(intent: Intent) {
        val workoutUpdateSignal = intent.getStringExtra(DataLayerListenerService.UPDATE_WORKOUTS)
        if (workoutUpdateSignal == null) {
            return
        }

        val workoutStore = workoutStoreRepository.getWorkoutStore()
        val healthConnectClient = HealthConnectClient.getOrCreate(activity)
        val db = AppDatabase.getDatabase(activity)
        val workoutHistoryDao = db.workoutHistoryDao()

        CoroutineScope(Dispatchers.IO).launch {
            val migratedWorkoutStore = migrateWorkoutStoreSetIdsIfNeeded(
                workoutStore,
                db,
                workoutStoreRepository
            )
            appViewModel.updateWorkoutStore(migratedWorkoutStore, false)
            workoutViewModel.updateWorkoutStore(migratedWorkoutStore)
            appViewModel.triggerUpdate()

            try {
                val currentYear = Calendar.getInstance().get(Calendar.YEAR)
                val latestWorkoutStore = workoutStoreRepository.getWorkoutStore()
                val age = currentYear - latestWorkoutStore.birthDateYear

                sendWorkoutsToHealthConnect(
                    healthConnectClient = healthConnectClient,
                    workouts = latestWorkoutStore.workouts,
                    workoutHistoryDao = workoutHistoryDao,
                    age = age,
                    weightKg = latestWorkoutStore.weightKg
                )
            } catch (exception: Exception) {
                Log.e(
                    "MyWorkoutAssistant",
                    "Error sending workouts to HealthConnect",
                    exception
                )
            }
        }
    }

    private fun showErrorLogsSyncedToastIfPresent(context: Context, intent: Intent) {
        val errorLogsSynced = intent.getStringExtra(DataLayerListenerService.ERROR_LOGS_SYNCED)
        val count = errorLogsSynced?.toIntOrNull() ?: return
        if (count <= 0) {
            return
        }
        Toast.makeText(
            context,
            "Received $count error log(s) from watch",
            Toast.LENGTH_SHORT
        ).show()
    }
}
