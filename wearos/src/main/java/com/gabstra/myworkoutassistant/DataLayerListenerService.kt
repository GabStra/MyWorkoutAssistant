package com.gabstra.myworkoutassistant

import android.content.Intent
import android.util.Log
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.logLargeString
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

class DataLayerListenerService : WearableListenerService() {
    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var workoutHistoryDao: WorkoutHistoryDao
    private lateinit var setHistoryDao: SetHistoryDao

    private var backupChunks = mutableListOf<String>()

    override fun onCreate() {
        super.onCreate()
        val db = AppDatabase.getDatabase(this)
        setHistoryDao = db.setHistoryDao()
        workoutHistoryDao = db.workoutHistoryDao()
    }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
        try{
            dataEvents.forEach { dataEvent ->
                val uri = dataEvent.dataItem.uri
                when (uri.path) {
                    WORKOUT_STORE_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val workoutStoreJson = dataMap.getString("json")
                        if(workoutStoreJson != null){
                            workoutStoreRepository.saveWorkoutStoreFromJson(workoutStoreJson)
                            val intent = Intent(INTENT_ID).apply {
                                putExtra("workoutStoreJson", workoutStoreJson)
                            }
                            sendBroadcast(intent)
                        }
                    }
                    BACKUP_CHUNK_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val backupChunk = dataMap.getString("chunk")

                        if (backupChunk != null) {
                            Log.d("CHUNK", backupChunk)

                            if(backupChunk == "START"){
                                backupChunks.clear()
                            }else{
                                backupChunks.add(backupChunk)
                            }

                            // Check if this is the last chunk
                            val isLastChunk = dataMap.getBoolean("isLastChunk", false)

                            if (isLastChunk) {
                                // Combine all chunks and reconstruct the backup
                                val backupJson = backupChunks.joinToString("")
                                val appBackup = fromJSONtoAppBackup(backupJson)
                                workoutStoreRepository.saveWorkoutStore(appBackup.WorkoutStore)

                                scope.launch {
                                    workoutHistoryDao.deleteAll()
                                    setHistoryDao.deleteAll()
                                    workoutHistoryDao.insertAll(*appBackup.WorkoutHistories.toTypedArray())
                                    setHistoryDao.insertAll(*appBackup.SetHistories.toTypedArray())
                                }

                                val intent = Intent(INTENT_ID).apply {
                                    putExtra("appBackupJson", backupJson)
                                }
                                sendBroadcast(intent)

                                backupChunks.clear()
                            }
                        }
                    }
                }
            }
        }catch (exception: Exception) {
            exception.printStackTrace()
            backupChunks.clear()
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
    }
}