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
import com.gabstra.myworkoutassistant.shared.WorkoutStoreValidationException
import com.gabstra.myworkoutassistant.shared.getEffectiveMaxHeartRate
import com.gabstra.myworkoutassistant.shared.validateWorkoutStoreForRuntimeUse
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
            try {
                validateWorkoutStoreForRuntimeUse(workoutStore)
            } catch (exception: WorkoutStoreValidationException) {
                Log.e(
                    "MyWorkoutAssistant",
                    "Ignoring synced workout update because workout-store validation failed: ${exception.userMessage}"
                )
                activity.runOnUiThread {
                    Toast.makeText(
                        activity,
                        "Ignored synced workout update: ${exception.message}",
                        Toast.LENGTH_LONG
                    ).show()
                }
                return@launch
            }
            appViewModel.updateWorkoutStore(workoutStore, false)
            workoutViewModel.applyExternalSyncWorkoutStore(workoutStore)
            appViewModel.triggerUpdate()

            val currentYear = Calendar.getInstance().get(Calendar.YEAR)
            val latestWorkoutStore = workoutStoreRepository.getWorkoutStore()
            val age = currentYear - latestWorkoutStore.birthDateYear

            try {
                sendWorkoutsToHealthConnect(
                    healthConnectClient = healthConnectClient,
                    workouts = latestWorkoutStore.workouts,
                    workoutHistoryDao = workoutHistoryDao,
                    age = age,
                    weightKg = latestWorkoutStore.weightKg,
                    female = latestWorkoutStore.sex,
                    vo2MaxMlKgMin = latestWorkoutStore.estimatedVo2MaxMlKgMin
                )
            } catch (exception: Exception) {
                Log.e(
                    "MyWorkoutAssistant",
                    "Error sending workouts to HealthConnect",
                    exception
                )
            }

            try {
                val histories = workoutHistoryDao.getAllWorkoutHistoriesByIsDone()
                val effectiveHrMax = getEffectiveMaxHeartRate(
                    age,
                    latestWorkoutStore.measuredMaxHeartRate,
                )
                val runEstimate = estimateVo2MaxFromRecentRuns(histories, effectiveHrMax)
                val updatedStore = refreshVo2MaxEstimate(latestWorkoutStore, age, runEstimate)
                if (updatedStore != null) {
                    workoutStoreRepository.saveWorkoutStore(updatedStore)
                    appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore(), false)
                }
            } catch (exception: Exception) {
                Log.e(
                    "MyWorkoutAssistant",
                    "Error refreshing the VO2max estimate",
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
            "Imported $count error log(s) from your watch.",
            Toast.LENGTH_SHORT
        ).show()
    }
}
