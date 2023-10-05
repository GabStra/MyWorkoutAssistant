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

        dataClient.putDataItem(request).addOnSuccessListener {
            android.util.Log.d("FIRE_SOME_DATA","Success")
        }.addOnCanceledListener {
            android.util.Log.d("FIRE_SOME_DATA","Cancel")
        }.addOnFailureListener {
            android.util.Log.d("FIRE_SOME_DATA","Failure")
        }
    } catch (cancellationException: CancellationException) {
        android.util.Log.d("FIRE_SOME_DATA","CANCELED")
        cancellationException.printStackTrace()
    } catch (exception: Exception) {
        android.util.Log.d("FIRE_SOME_DATA","${exception.message}")
        exception.printStackTrace()
    }
}