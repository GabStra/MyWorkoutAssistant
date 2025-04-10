package com.gabstra.myworkoutassistant

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.gabstra.myworkoutassistant.data.combineChunks
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao

class DataLayerListenerService : WearableListenerService() {
    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var workoutHistoryDao: WorkoutHistoryDao
    private lateinit var setHistoryDao: SetHistoryDao
    private lateinit var exerciseInfoDao: ExerciseInfoDao
    private lateinit var workoutRecordDao: WorkoutRecordDao

    private val sharedPreferences by lazy { getSharedPreferences("backup_state", Context.MODE_PRIVATE) }

    private var backupChunks: MutableList<ByteArray> = mutableListOf()

    private var expectedChunks: Int
        get() = sharedPreferences.getInt("expectedChunks", 0)
        set(value) {
            sharedPreferences.edit() { putInt("expectedChunks", value) }
        }

    private var ignoreUntilStartOrEnd: Boolean
        get() = sharedPreferences.getBoolean("ignoreUntilStartOrEnd", false)
        set(value) {
            sharedPreferences.edit() { putBoolean("ignoreUntilStartOrEnd", value) }
        }

    private var hasStartedSync: Boolean
        get() = sharedPreferences.getBoolean("hasStartedSync", false)
        set(value) {
            sharedPreferences.edit() { putBoolean("hasStartedSync", value) }
        }

    private var currentTransactionId: String?
        get() = sharedPreferences.getString("currentTransactionId", null)
        set(value) {
            if (value == null) {
                sharedPreferences.edit() { remove("currentTransactionId") }
            } else {
                sharedPreferences.edit() { putString("currentTransactionId", value) }
            }
        }

    private lateinit var workoutScheduleDao: WorkoutScheduleDao

    private lateinit var context : WearableListenerService

    override fun onCreate() {
        super.onCreate()
        val db = AppDatabase.getDatabase(this)
        context = this
        setHistoryDao = db.setHistoryDao()
        workoutHistoryDao = db.workoutHistoryDao()
        exerciseInfoDao = db.exerciseInfoDao()
        workoutScheduleDao = db.workoutScheduleDao()
        workoutRecordDao = db.workoutRecordDao()
    }

    private val handler = Handler(Looper.getMainLooper())
    private val timeoutRunnable = Runnable {
        Log.d("DataLayerListenerService", "Timeout triggered")

        val intent = Intent(INTENT_ID).apply {
            putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
        }.apply { setPackage(packageName) }
        sendBroadcast(intent)

        backupChunks.clear()
        expectedChunks = 0
        hasStartedSync = false
        currentTransactionId = null
        ignoreUntilStartOrEnd = true
    }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        try {
            dataEvents.forEach { dataEvent ->
                val uri = dataEvent.dataItem.uri
                when (uri.path) {
                    WORKOUT_STORE_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val compressedJson = dataMap.getByteArray("compressedJson")
                        val workoutStoreJson = decompressToString(compressedJson!!)
                        workoutStoreRepository.saveWorkoutStoreFromJson(workoutStoreJson)
                        val intent = Intent(INTENT_ID).apply {
                            putExtra(WORKOUT_STORE_JSON, workoutStoreJson)
                        }
                        sendBroadcast(intent)
                    }

                    BACKUP_CHUNK_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap

                        Log.d("MainActivity", "Received backup chunk")

                        val isStart = dataMap.getBoolean("isStart", false)
                        val isLastChunk = dataMap.getBoolean("isLastChunk", false)
                        val backupChunk = dataMap.getByteArray("chunk")
                        val transactionId = dataMap.getString("transactionId")

                        val shouldStop = (isStart && hasStartedSync) ||
                                (backupChunk != null && !hasStartedSync) ||
                                (currentTransactionId != null && currentTransactionId != transactionId)

                        if (!ignoreUntilStartOrEnd && shouldStop) {
                            handler.removeCallbacks(timeoutRunnable)
                            val intent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
                            }.apply { setPackage(packageName) }

                            sendBroadcast(intent)

                            backupChunks.clear()
                            expectedChunks = 0
                            hasStartedSync = false
                            currentTransactionId = null

                            ignoreUntilStartOrEnd = true
                            return
                        }

                        if (isStart) {
                            if (dataMap.containsKey("chunksCount")) {
                                expectedChunks = dataMap.getInt("chunksCount", 0)
                            }

                            backupChunks.clear()
                            hasStartedSync = true
                            ignoreUntilStartOrEnd = false
                            currentTransactionId = transactionId

                            val intent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_START_JSON, APP_BACKUP_START_JSON)
                            }.apply { setPackage(packageName) }
                            sendBroadcast(intent)

                            handler.removeCallbacks(timeoutRunnable)
                            handler.postDelayed(timeoutRunnable, 10000)
                        }

                        if (backupChunk != null && !ignoreUntilStartOrEnd) {
                            handler.removeCallbacks(timeoutRunnable)
                            handler.postDelayed(timeoutRunnable, 10000)

                            backupChunks.add(backupChunk)

                            val progress = backupChunks.size.toFloat() / expectedChunks
                            val progressIntent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_PROGRESS_UPDATE, "$progress")
                            }.apply { setPackage(packageName) }
                            sendBroadcast(progressIntent)
                        }

                        if (isLastChunk) {
                            if (!ignoreUntilStartOrEnd) {
                                handler.removeCallbacks(timeoutRunnable)
                                val backupData = combineChunks(backupChunks)
                                val jsonBackup = decompressToString(backupData)

                                val appBackup = fromJSONtoAppBackup(jsonBackup)
                                workoutStoreRepository.saveWorkoutStore(appBackup.WorkoutStore)

                                runBlocking {
                                    val allSchedules = workoutScheduleDao.getAllSchedules()

                                    val scheduler = WorkoutAlarmScheduler(context)
                                    for (schedule in allSchedules) {
                                        scheduler.cancelSchedule(schedule)
                                    }

                                    workoutScheduleDao.deleteAll()

                                    val insertWorkoutHistoriesJob =
                                        scope.launch(start = CoroutineStart.LAZY) {
                                            workoutHistoryDao.insertAllWithVersionCheck(*appBackup.WorkoutHistories.toTypedArray())
                                        }

                                    val insertSetHistoriesJob =
                                        scope.launch(start = CoroutineStart.LAZY) {
                                            setHistoryDao.insertAllWithVersionCheck(*appBackup.SetHistories.toTypedArray())
                                        }

                                    val insertExerciseInfosJob =
                                        scope.launch(start = CoroutineStart.LAZY) {
                                            exerciseInfoDao.insertAllWithVersionCheck(*appBackup.ExerciseInfos.toTypedArray())
                                        }

                                    val insertWorkoutSchedulesJob =
                                        scope.launch(start = CoroutineStart.LAZY) {
                                            workoutScheduleDao.deleteAll()
                                            workoutScheduleDao.insertAll(*appBackup.WorkoutSchedules.toTypedArray())
                                        }

                                    val insertWorkoutRecordsJob =
                                        scope.launch(start = CoroutineStart.LAZY) {
                                            workoutRecordDao.deleteAll()
                                            workoutRecordDao.insertAll(*appBackup.WorkoutRecords.toTypedArray())
                                        }

                                    joinAll(
                                        insertWorkoutHistoriesJob,
                                        insertSetHistoriesJob,
                                        insertExerciseInfosJob,
                                        insertWorkoutSchedulesJob,
                                        insertWorkoutRecordsJob
                                    )

                                    val intent = Intent(INTENT_ID).apply {
                                        putExtra(APP_BACKUP_END_JSON, APP_BACKUP_END_JSON)
                                    }.apply { setPackage(packageName) }
                                    //intent.apply { setPackage(packageName) }
                                    sendBroadcast(intent)

                                    backupChunks.clear()
                                    expectedChunks = 0
                                    hasStartedSync = false
                                    ignoreUntilStartOrEnd = false
                                    currentTransactionId = null
                                }
                            }

                            backupChunks.clear()
                            expectedChunks = 0
                            hasStartedSync = false
                            ignoreUntilStartOrEnd = false
                            currentTransactionId = null
                        }
                    }
                }
            }
        } catch (exception: Exception) {
            exception.printStackTrace()
            Log.e("DataLayerListenerService", "Error processing data", exception)
            handler.removeCallbacks(timeoutRunnable)
            val intent = Intent(INTENT_ID).apply {
                putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
            }
            sendBroadcast(intent)
            backupChunks.clear()
            expectedChunks = 0
            hasStartedSync = false
            ignoreUntilStartOrEnd = true
        } finally {
            super.onDataChanged(dataEvents)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    companion object {
        private const val WORKOUT_STORE_PATH = "/workoutStore"
        private const val BACKUP_CHUNK_PATH = "/backupChunkPath"
        const val INTENT_ID = "com.gabstra.myworkoutassistant.workoutstore"
        const val WORKOUT_STORE_JSON = "workoutStoreJson"
        const val APP_BACKUP_START_JSON = "appBackupStartJson"
        const val APP_BACKUP_END_JSON = "appBackupEndJson"
        const val APP_BACKUP_FAILED = "appBackupFailed"
        const val APP_BACKUP_PROGRESS_UPDATE = "progress_update"
    }
}
