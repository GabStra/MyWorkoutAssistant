package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Publishes the phone's profile list so paired watches can show and follow it.
 *
 * A DataItem reaches every connected node at once, which is what we want here: the list is
 * identical for all watches, only the selection differs and that is the phone's.
 */
suspend fun pushProfileIndexToWatches(context: Context) {
    val appContext = context.applicationContext
    withContext(Dispatchers.IO) {
        try {
            val request = PutDataMapRequest.create(DataLayerPaths.PROFILE_INDEX_PATH).apply {
                dataMap.putString("indexJson", Profiles.exportIndexJson(appContext))
            }.asPutDataRequest().setUrgent()
            Tasks.await(Wearable.getDataClient(appContext).putDataItem(request))
        } catch (exception: Exception) {
            Log.w("ProfileIndexSync", "Failed to publish the profile index to watches", exception)
        }
    }
}
