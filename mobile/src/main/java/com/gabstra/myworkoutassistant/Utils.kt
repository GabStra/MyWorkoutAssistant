package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.gson.Gson
import java.util.concurrent.CancellationException

fun sendWorkoutStore(dataClient: DataClient, workoutStore: WorkoutStore) {
    try {
        val gson = Gson()
        val jsonString = gson.toJson(workoutStore)

        val request = PutDataMapRequest.create("/workoutStore").apply {
            dataMap.putString("json",jsonString)
            dataMap.putString("timestamp",System.currentTimeMillis().toString())
        }.asPutDataRequest().setUrgent()

        dataClient.putDataItem(request)
    } catch (cancellationException: CancellationException) {
        cancellationException.printStackTrace()
    } catch (exception: Exception) {
        exception.printStackTrace()
    }
}