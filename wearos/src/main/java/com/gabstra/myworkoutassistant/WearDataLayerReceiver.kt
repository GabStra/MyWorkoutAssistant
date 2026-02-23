package com.gabstra.myworkoutassistant

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import android.widget.Toast
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState

internal class WearDataLayerReceiver(
    private val navController: NavController,
    private val appViewModel: AppViewModel,
    private val workoutStoreRepository: WorkoutStoreRepository,
    private val activity: Activity
) : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        activity.run {
            try {
                handleBackupStart(intent)
                handleWorkoutStoreRefresh(intent)
                handleBackupEnd(intent)
                handleBackupProgress(intent)
                handleSyncComplete(intent, context)
                handleBackupFailed(intent, context)
            } catch (exception: Exception) {
                Log.e("WearDataLayerReceiver", "Error processing data", exception)
            }
        }
    }

    private fun handleBackupStart(intent: Intent) {
        val appBackupStartJson = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_START_JSON)
        val startAccepted = intent.getBooleanExtra(
            DataLayerListenerService.APP_BACKUP_START_ACCEPTED,
            false
        )
        if (appBackupStartJson == null || !startAccepted) {
            return
        }
        Log.d("DataLayerSync", "Received APP_BACKUP_START_JSON - triggering loading screen")
        appViewModel.setBackupProgress(0f)

        val currentRoute = navController.currentBackStackEntry?.destination?.route
        if (currentRoute != Screen.Workout.route) {
            navController.navigate(Screen.Loading.route)
        }
    }

    private fun handleWorkoutStoreRefresh(intent: Intent) {
        val workoutStoreJson = intent.getStringExtra(DataLayerListenerService.WORKOUT_STORE_JSON)
        val appBackupEndJson = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_END_JSON)
        if (workoutStoreJson == null && appBackupEndJson == null) {
            return
        }
        appViewModel.resetWorkoutStore()
        appViewModel.updateWorkoutStore(workoutStoreRepository.getWorkoutStore())
        if (workoutStoreJson != null) {
            Toast.makeText(activity, "Workouts updated", Toast.LENGTH_SHORT).show()
        }
    }

    private fun handleBackupEnd(intent: Intent) {
        val appBackupEndJson = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_END_JSON)
        if (appBackupEndJson == null) {
            return
        }
        Log.d("DataLayerSync", "Received APP_BACKUP_END_JSON - dismissing loading screen")
        val currentRoute = navController.currentBackStackEntry?.destination?.route
        if (currentRoute != Screen.Workout.route) {
            navController.navigate(Screen.WorkoutSelection.route) {
                popUpTo(0) { inclusive = true }
            }
        }
        WorkoutAlarmScheduler(activity).rescheduleAllWorkouts()
    }

    private fun handleBackupProgress(intent: Intent) {
        val appBackupProgress =
            intent.getStringExtra(DataLayerListenerService.APP_BACKUP_PROGRESS_UPDATE)
        val progress = appBackupProgress?.toFloatOrNull() ?: return
        appViewModel.setBackupProgress(progress)
    }

    private fun handleSyncComplete(intent: Intent, context: Context) {
        val syncComplete = intent.getStringExtra(DataLayerListenerService.SYNC_COMPLETE)
        if (syncComplete == null) {
            return
        }
        val transactionId = intent.getStringExtra(DataLayerListenerService.TRANSACTION_ID)
        appViewModel.markHistorySyncedForTransaction(transactionId)
        Log.d("DataLayerSync", "Received SYNC_COMPLETE - checking syncStatus before showing toast")
        val workoutState = appViewModel.workoutState.value
        val isWorkoutActive = workoutState !is WorkoutState.Completed
        if (appViewModel.syncStatus.value != AppViewModel.SyncStatus.Syncing && !isWorkoutActive) {
            Toast.makeText(context, "Sync completed", Toast.LENGTH_SHORT).show()
        }
    }

    private fun handleBackupFailed(intent: Intent, context: Context) {
        val appBackupFailed = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_FAILED)
        if (appBackupFailed == null) {
            return
        }
        Log.d("DataLayerSync", "Received APP_BACKUP_FAILED - sync failed")
        appViewModel.setBackupProgress(0f)
        appViewModel.resetSyncStatus()

        val currentRoute = navController.currentBackStackEntry?.destination?.route
        if (currentRoute == Screen.Loading.route) {
            navController.navigate(Screen.WorkoutSelection.route) {
                popUpTo(0) { inclusive = true }
            }
        }

        val workoutState = appViewModel.workoutState.value
        val isWorkoutActive = workoutState !is WorkoutState.Completed
        if (appViewModel.syncStatus.value != AppViewModel.SyncStatus.Syncing && !isWorkoutActive) {
            Toast.makeText(context, "Sync failed", Toast.LENGTH_SHORT).show()
        }
    }
}
