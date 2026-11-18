package com.gabstra.myworkoutassistant

import android.app.Activity
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.navigation.NavController
import com.gabstra.myworkoutassistant.R
import com.gabstra.myworkoutassistant.data.AppViewModel
import com.gabstra.myworkoutassistant.data.Screen
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.datalayer.SyncPhase
import com.gabstra.myworkoutassistant.shared.workout.state.WorkoutState
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

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
        appViewModel.setBackupSyncPhase(SyncPhase.TRANSFERRING)

        val currentRoute = navController.currentBackStackEntry?.destination?.route
        if (currentRoute != Screen.Workout.route && currentRoute != Screen.Loading.route) {
            navController.navigate(Screen.Loading.route)
        }
    }

    private fun handleWorkoutStoreRefresh(intent: Intent) {
        val workoutStoreJson = intent.getStringExtra(DataLayerListenerService.WORKOUT_STORE_JSON)
        val appBackupEndJson = intent.getStringExtra(DataLayerListenerService.APP_BACKUP_END_JSON)
        if (workoutStoreJson == null && appBackupEndJson == null) {
            return
        }
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val refreshedWorkoutStore = workoutStoreRepository.getWorkoutStore()
                appViewModel.applyExternalSyncWorkoutStore(refreshedWorkoutStore)
                appViewModel.refreshSelectedWorkoutRecord()
            } catch (exception: Exception) {
                Log.e("WearDataLayerReceiver", "Error refreshing workout store", exception)
            }
        }
/*        if (workoutStoreJson != null) {
            Toast.makeText(activity, activity.getString(R.string.wear_sync_workouts_updated), Toast.LENGTH_SHORT).show()
        }*/
    }

    private fun handleBackupEnd(intent: Intent) {
        val appBackupEndJson =
            intent.getStringExtra(DataLayerListenerService.APP_BACKUP_END_JSON) ?: return
        // Another profile transaction follows in this sync: keep the loader and its stage
        // sequence continuous instead of dropping back to the workout screen.
        // shortcut: if the promised follow-up transaction never arrives the loader stays up
        // (the next SYNC_REQUEST's start deadline recovers it only once a request exists);
        // upgrade with a bounded wait for the follow-up when multi-profile syncs grow.
        if (intent.getBooleanExtra(DataLayerListenerService.APP_BACKUP_MORE_COMING, false)) {
            Log.d("DataLayerSync", "Backup end with follow-up transaction; keeping loading screen")
            return
        }
        Log.d("DataLayerSync", "Received APP_BACKUP_END_JSON - dismissing loading screen")
        appViewModel.setBackupSyncPhase(SyncPhase.COMPLETED)
        val currentRoute = navController.currentBackStackEntry?.destination?.route
        if (currentRoute == Screen.Loading.route) {
            CoroutineScope(Dispatchers.Main).launch {
                delay(800L)
                if (navController.currentBackStackEntry?.destination?.route == Screen.Loading.route) {
                    navController.navigate(Screen.WorkoutSelection.route) {
                        popUpTo(0) { inclusive = true }
                    }
                }
            }
        }
        // Workout alarms are re-registered in DataLayerListenerService after backup DB commit.
    }

    private fun handleBackupProgress(intent: Intent) {
        val appBackupProgress =
            intent.getStringExtra(DataLayerListenerService.APP_BACKUP_PROGRESS_UPDATE)
        val progress = appBackupProgress?.toFloatOrNull() ?: return
        appViewModel.setBackupProgress(progress)
        SyncPhase.fromWireValue(
            intent.getStringExtra(DataLayerListenerService.APP_BACKUP_PHASE_UPDATE)
        )?.let { phase ->
            appViewModel.setBackupSyncPhase(phase)
            if (phase == SyncPhase.CONNECTING) {
                // Show the loading screen as soon as the handshake starts so the
                // watch mirrors the phone's stage sequence from the first step.
                val currentRoute = navController.currentBackStackEntry?.destination?.route
                if (currentRoute != Screen.Workout.route && currentRoute != Screen.Loading.route) {
                    navController.navigate(Screen.Loading.route)
                }
            }
        }
    }

    private fun handleSyncComplete(intent: Intent, context: Context) {
        val syncComplete = intent.getStringExtra(DataLayerListenerService.SYNC_COMPLETE) ?: return
        val transactionId = intent.getStringExtra(DataLayerListenerService.TRANSACTION_ID)
        appViewModel.markHistorySyncedForTransaction(transactionId)
        appViewModel.setBackupSyncPhase(SyncPhase.COMPLETED)
        Log.d("DataLayerSync", "Received SYNC_COMPLETE - checking syncStatus before showing toast")
        val workoutState = appViewModel.workoutState.value
        val isWorkoutActive = workoutState !is WorkoutState.Completed
/*        if (appViewModel.syncStatus.value != AppViewModel.SyncStatus.Syncing && !isWorkoutActive) {
            Toast.makeText(context, context.getString(R.string.wear_sync_finished), Toast.LENGTH_SHORT).show()
        }*/
    }

    private fun handleBackupFailed(intent: Intent, context: Context) {
        val appBackupFailed =
            intent.getStringExtra(DataLayerListenerService.APP_BACKUP_FAILED) ?: return
        Log.d("DataLayerSync", "Received APP_BACKUP_FAILED - sync failed")
        appViewModel.setBackupProgress(0f)
        appViewModel.setBackupSyncPhase(SyncPhase.CONNECTING)
        appViewModel.resetSyncStatus()

        val currentRoute = navController.currentBackStackEntry?.destination?.route
        if (currentRoute == Screen.Loading.route) {
            navController.navigate(Screen.WorkoutSelection.route) {
                popUpTo(0) { inclusive = true }
            }
        }

        val workoutState = appViewModel.workoutState.value
        val isWorkoutActive = workoutState !is WorkoutState.Completed
/*        if (appViewModel.syncStatus.value != AppViewModel.SyncStatus.Syncing && !isWorkoutActive) {
            Toast.makeText(context, context.getString(R.string.wear_sync_failed_try_again), Toast.LENGTH_SHORT).show()
        }*/
    }
}
