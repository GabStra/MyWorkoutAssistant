package com.gabstra.myworkoutassistant

import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.gabstra.myworkoutassistant.data.combineChunks
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.ExerciseInfoDao
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
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

class DataLayerListenerService : WearableListenerService() {
    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var workoutHistoryDao: WorkoutHistoryDao
    private lateinit var setHistoryDao: SetHistoryDao
    private lateinit var exerciseInfoDao: ExerciseInfoDao

    private var backupChunks = mutableListOf<ByteArray>()

    private var expectedChunks = 0

    private var hasStartedSync = false

    private var ignoreUntilStartOrEnd = false

    private var currentTransactionId : String? = null

    override fun onCreate() {
        super.onCreate()
        val db = AppDatabase.getDatabase(this)
        setHistoryDao = db.setHistoryDao()
        workoutHistoryDao = db.workoutHistoryDao()
        exerciseInfoDao = db.exerciseInfoDao()
    }

    private val handler = Handler(Looper.getMainLooper())
    private val timeoutRunnable = Runnable {
        val intent = Intent(INTENT_ID).apply {
            putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
        }
        sendBroadcast(intent)
        currentTransactionId = null
        ignoreUntilStartOrEnd = true
    }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        try{
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

                        val isStart = dataMap.getBoolean("isStart",false)
                        val isLastChunk = dataMap.getBoolean("isLastChunk", false)

                        if(dataMap.containsKey("chunksCount")){
                            expectedChunks = dataMap.getInt("chunksCount",0)
                        }
                        val backupChunk = dataMap.getByteArray("chunk")

                        val transactionId = dataMap.getString("transactionId")

                        if(currentTransactionId != null && currentTransactionId != transactionId){
                            return
                        }
                        
                        val shouldStop = (isStart && hasStartedSync) || (backupChunk != null && !hasStartedSync)

                        if(!ignoreUntilStartOrEnd && shouldStop) {
                            handler.removeCallbacks(timeoutRunnable)
                            val intent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
                            }

                            sendBroadcast(intent)
                            currentTransactionId = null
                            ignoreUntilStartOrEnd = true
                            return
                        }

                        if(isStart) {
                            backupChunks.clear()

                            val intent = Intent(INTENT_ID).apply {
                                putExtra(APP_BACKUP_START_JSON, APP_BACKUP_START_JSON)
                            }
                            sendBroadcast(intent)
                            hasStartedSync = true
                            ignoreUntilStartOrEnd = false
                            currentTransactionId = transactionId
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
                            }
                            sendBroadcast(progressIntent)
                        }

                        if (isLastChunk) {
                            if(!ignoreUntilStartOrEnd){
                                handler.removeCallbacks(timeoutRunnable)
                                val backupData = combineChunks(backupChunks)
                                val jsonBackup = decompressToString(backupData)

                                val appBackup = fromJSONtoAppBackup(jsonBackup)
                                workoutStoreRepository.saveWorkoutStore(appBackup.WorkoutStore)

                                runBlocking {
                                    val insertWorkoutHistoriesJob = scope.launch(start = CoroutineStart.LAZY) {
                                        workoutHistoryDao.insertAllWithVersionCheck(*appBackup.WorkoutHistories.toTypedArray())
                                    }

                                    val insertSetHistoriesJob = scope.launch(start = CoroutineStart.LAZY) {
                                        setHistoryDao.insertAllWithVersionCheck(*appBackup.SetHistories.toTypedArray())
                                    }

                                    val insertExerciseInfosJob = scope.launch(start = CoroutineStart.LAZY) {
                                        exerciseInfoDao.insertAllWithVersionCheck(*appBackup.ExerciseInfos.toTypedArray())
                                    }

                                    joinAll(insertWorkoutHistoriesJob, insertSetHistoriesJob, insertExerciseInfosJob)

                                    val intent = Intent(INTENT_ID).apply {
                                        putExtra(APP_BACKUP_END_JSON, APP_BACKUP_END_JSON)
                                    }
                                    intent.apply { setPackage(packageName) }
                                    sendBroadcast(intent)

                                    backupChunks.clear()
                                    expectedChunks = 0
                                    hasStartedSync = false
                                    ignoreUntilStartOrEnd = false
                                    currentTransactionId = null
                                }
                                return
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
        }catch (exception: Exception) {
            exception.printStackTrace()
            Log.e("DataLayerListenerService", "Error processing data", exception)
            val intent = Intent(INTENT_ID).apply {
                putExtra(APP_BACKUP_FAILED, APP_BACKUP_FAILED)
            }
            sendBroadcast(intent)
            backupChunks.clear()
            expectedChunks = 0
            hasStartedSync = false
            ignoreUntilStartOrEnd = true
        }finally {
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