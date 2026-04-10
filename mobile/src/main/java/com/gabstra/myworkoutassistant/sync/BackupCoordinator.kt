package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import com.gabstra.myworkoutassistant.saveWorkoutStoreToExternalStorage
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

object BackupCoordinator {
    private const val TAG = "BackupCoordinator"
    private const val PHONE_PERSIST_DEBOUNCE_MS = 2_000L
    private const val WEAR_PERSIST_DEBOUNCE_MS = 60_000L

    enum class Trigger {
        PHONE_PERSIST,
        WEAR_PERSIST
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
    private val mutex = Mutex()

    private var backupJob: Job? = null
    private var pendingTrigger: Trigger? = null

    suspend fun onWorkoutStorePersisted(
        context: Context,
        trigger: Trigger
    ) {
        val appContext = context.applicationContext
        mutex.withLock {
            when (trigger) {
                Trigger.PHONE_PERSIST -> {
                    scheduleLocked(
                        context = appContext,
                        trigger = trigger,
                        delayMs = PHONE_PERSIST_DEBOUNCE_MS
                    )
                    Log.d(TAG, "Scheduled phone-originated backup")
                }

                Trigger.WEAR_PERSIST -> {
                    if (pendingTrigger == Trigger.PHONE_PERSIST) {
                        Log.d(TAG, "Skipped wear reschedule because a sooner phone backup is pending")
                        return
                    }

                    scheduleLocked(
                        context = appContext,
                        trigger = trigger,
                        delayMs = WEAR_PERSIST_DEBOUNCE_MS
                    )
                    Log.d(TAG, "Scheduled wear-originated backup")
                }
            }
        }
    }

    suspend fun flushPendingBackup(context: Context) {
        val appContext = context.applicationContext
        val triggerToFlush = mutex.withLock {
            val trigger = pendingTrigger
            if (trigger == null) {
                return@withLock null
            }
            backupJob?.cancel()
            backupJob = null
            pendingTrigger = null
            trigger
        }
        if (triggerToFlush == null) {
            return
        }

        Log.d(TAG, "Flushing pending backup for trigger=$triggerToFlush")
        performBackup(appContext, triggerToFlush)
    }

    private fun scheduleLocked(
        context: Context,
        trigger: Trigger,
        delayMs: Long
    ) {
        backupJob?.cancel()
        pendingTrigger = trigger
        backupJob = scope.launch {
            delay(delayMs)
            mutex.withLock {
                backupJob = null
                pendingTrigger = null
            }
            performBackup(context, trigger)
        }
    }

    private suspend fun performBackup(
        context: Context,
        trigger: Trigger
    ) {
        runCatching {
            val db = AppDatabase.getDatabase(context)
            val workoutStore = withContext(Dispatchers.IO) {
                WorkoutStoreRepository(context.filesDir).getWorkoutStore()
            }
            saveWorkoutStoreToExternalStorage(context, workoutStore, db)
            Log.d(TAG, "Completed backup for trigger=$trigger")
        }.onFailure { exception ->
            Log.e(TAG, "Failed backup for trigger=$trigger", exception)
        }
    }
}
