package com.gabstra.myworkoutassistant

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import androidx.core.content.edit
import com.gabstra.myworkoutassistant.data.combineChunks
import com.gabstra.myworkoutassistant.scheduling.WorkoutAlarmScheduler
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutRecordDao
import com.gabstra.myworkoutassistant.shared.WorkoutScheduleDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.WearableListenerService
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlin.io.encoding.Base64
import kotlin.io.encoding.ExperimentalEncodingApi

class DataLayerListenerService : WearableListenerService() {
    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var workoutHistoryDao: WorkoutHistoryDao
    private lateinit var setHistoryDao: SetHistoryDao
    private lateinit var exerciseInfoDao: ExerciseInfoDao
    private lateinit var workoutRecordDao: WorkoutRecordDao

    private val sharedPreferences by lazy { getSharedPreferences("backup_state", Context.MODE_PRIVATE) }
    private val gson = Gson()

    @OptIn(ExperimentalEncodingApi::class)
    private var backupChunks: MutableList<ByteArray>
        get() {
            val jsonString = sharedPreferences.getString("backup_chunks", null)
            if (jsonString.isNullOrEmpty()) {
                return mutableListOf()
            }
            return try {
                val typeToken = object : TypeToken<List<String>>() {}.type
                val base64Strings: List<String> = gson.fromJson(jsonString, typeToken)
                base64Strings.mapNotNull { base64String ->
                    try {
                        Base64.decode(base64String)
                    } catch (e: IllegalArgumentException) {
                        Log.e("DataLayerListenerService", "Failed to decode Base64 string for a chunk: ${e.message}")
                        null // Skip corrupted chunk data
                    }
                }.toMutableList()
            } catch (e: Exception) { // Catching broader exceptions from Gson parsing or list mapping
                Log.e("DataLayerListenerService", "Failed to parse backupChunks from SharedPreferences with Gson: ${e.message}", e)
                // Clear corrupted data and return an empty list
                sharedPreferences.edit { remove("backup_chunks") }
                mutableListOf()
            }
        }
        set(value) {
            if (value.isEmpty()) {
                sharedPreferences.edit { remove("backup_chunks") }
            } else {
                try {
                    val base64Strings = value.map { byteArray ->
                        Base64.encode(byteArray)
                    }
                    val jsonString = gson.toJson(base64Strings)
                    sharedPreferences.edit { putString("backup_chunks", jsonString) }
                } catch (e: Exception) { // Catching broader exceptions from Gson parsing or list mapping
                    Log.e("DataLayerListenerService", "Failed to save backupChunks to SharedPreferences with Gson: ${e.message}", e)
                    // Potentially clear or leave stale data depending on desired error handling
                }
            }
        }

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

    @Volatile // Ensure visibility across threads
    private var timeoutOperationCancelled = false

    private val timeoutRunnable = Runnable {
        if (timeoutOperationCancelled) {
            return@Runnable // Exit if cancelled
        }
        Log.d("DataLayerListenerService", "Timeout triggered")

        val intent = Intent(INTENT_ID).apply {
            putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
            setPackage(packageName)
        }
        sendBroadcast(intent)

        backupChunks = mutableListOf()
        expectedChunks = 0
        hasStartedSync = false
        currentTransactionId = null
        ignoreUntilStartOrEnd = true
    }

    private fun postTimeout() {
        timeoutOperationCancelled = false // Reset flag before posting
        handler.postDelayed(timeoutRunnable, 30000)
    }

    // Helper function to remove timeout
    private fun removeTimeout() {
        timeoutOperationCancelled = true // Set flag to indicate cancellation intent
        handler.removeCallbacks(timeoutRunnable)
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

                        val isStart = dataMap.getBoolean("isStart", false)
                        val isLastChunk = dataMap.getBoolean("isLastChunk", false)
                        val backupChunk = dataMap.getByteArray("chunk")
                        val transactionId = dataMap.getString("transactionId")


                        val shouldStop = (isStart && hasStartedSync) ||
                                (backupChunk != null && !hasStartedSync) ||
                                (currentTransactionId != null && currentTransactionId != transactionId)

                        Log.d("DataLayerListenerService", "ignoreUntilStartOrEnd: $ignoreUntilStartOrEnd hasBackupChunk: ${backupChunk != null} isStart: $isStart isLastChunk: $isLastChunk transactionId: $transactionId shouldStop: $shouldStop")

                        if (!ignoreUntilStartOrEnd && shouldStop) {
                            removeTimeout()
                            val intent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
                                setPackage(packageName)
                            }

                            sendBroadcast(intent)

                            backupChunks = mutableListOf()
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

                            Log.d("DataLayerListenerService", "Backup started with expected chunks: $expectedChunks, transactionId: $transactionId")

                            backupChunks = mutableListOf()
                            hasStartedSync = true
                            ignoreUntilStartOrEnd = false
                            currentTransactionId = transactionId

                            val intent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_START_JSON, APP_BACKUP_START_JSON)
                            }.apply { setPackage(packageName) }
                            sendBroadcast(intent)

                            removeTimeout()
                        }

                        if (backupChunk != null && !ignoreUntilStartOrEnd) {
                            removeTimeout()
                            postTimeout()

                            backupChunks = backupChunks.toMutableList().apply {
                                add(backupChunk)
                            }

                            val progress = backupChunks.size.toFloat() / expectedChunks

                            val progressIntent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_PROGRESS_UPDATE, "$progress")
                            }.apply { setPackage(packageName) }
                            sendBroadcast(progressIntent)
                        }

                        if (isLastChunk) {
                            if (!ignoreUntilStartOrEnd) {
                                removeTimeout()
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
                                        setPackage(packageName)
                                    }

                                    sendBroadcast(intent)

                                    backupChunks = mutableListOf()
                                    expectedChunks = 0
                                    hasStartedSync = false
                                    ignoreUntilStartOrEnd = false
                                    currentTransactionId = null
                                }
                            }

                            backupChunks = mutableListOf()
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
            removeTimeout()
            val intent = Intent(INTENT_ID).apply {
                putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
                setPackage(packageName)
            }
            sendBroadcast(intent)
            backupChunks = mutableListOf()
            expectedChunks = 0
            hasStartedSync = false
            ignoreUntilStartOrEnd = true
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
