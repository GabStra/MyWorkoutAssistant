package com.gabstra.myworkoutassistant

import android.content.Intent
import android.util.Log
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.decompressToString
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
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
                                putExtra(WORKOUT_STORE_JSON, workoutStoreJson)
                            }
                            sendBroadcast(intent)
                        }
                    }
                    BACKUP_CHUNK_PATH -> {
                        val dataMap = DataMapItem.fromDataItem(dataEvent.dataItem).dataMap
                        val backupChunk = dataMap.getString("chunk")

                        if (backupChunk != null) {
                            if(backupChunk == "START"){
                                backupChunks.clear()

                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(APP_BACKUP_START_JSON, APP_BACKUP_START_JSON)
                                }
                                sendBroadcast(intent)

                            }else{
                                backupChunks.add(backupChunk)
                            }

                            // Check if this is the last chunk
                            val isLastChunk = dataMap.getBoolean("isLastChunk", false)

                            if (isLastChunk) {
                                val backupData  = backupChunks.joinToString("")
                                val decompressedData = decompressToString(backupData.toByteArray())
                                val appBackup = fromJSONtoAppBackup(decompressedData)
                                workoutStoreRepository.saveWorkoutStore(appBackup.WorkoutStore)

                                scope.launch {
                                    workoutHistoryDao.deleteAll()
                                    setHistoryDao.deleteAll()
                                    workoutHistoryDao.insertAll(*appBackup.WorkoutHistories.toTypedArray())
                                    setHistoryDao.insertAll(*appBackup.SetHistories.toTypedArray())
                                }

                                val intent = Intent(INTENT_ID).apply {
                                    putExtra(APP_BACKUP_END_JSON, APP_BACKUP_END_JSON)
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
        const val WORKOUT_STORE_JSON = "workoutStoreJson"
        const val APP_BACKUP_START_JSON = "appBackupStartJson"
        const val APP_BACKUP_END_JSON = "appBackupEndJson"
    }
}