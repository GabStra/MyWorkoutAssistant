package com.gabstra.myworkoutassistant

import android.content.Intent
import android.util.Log
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.google.android.gms.wearable.DataEventBuffer
import com.google.android.gms.wearable.DataMapItem
import com.google.android.gms.wearable.WearableListenerService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel

class DataLayerListenerService : WearableListenerService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val workoutStoreRepository by lazy { WorkoutStoreRepository(this.filesDir) }

    override fun onDataChanged(dataEvents: DataEventBuffer) {
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
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    companion object {
        private const val WORKOUT_STORE_PATH = "/workoutStore"
        const val INTENT_ID = "com.gabstra.myworkoutassistant.workoutstore"
    }
}