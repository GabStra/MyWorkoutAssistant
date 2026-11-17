package com.gabstra.myworkoutassistant.sync

import android.content.Context
import android.util.Log
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/**
 * Tells the phone which profile this watch follows.
 *
 * Without this the phone only ever pushes its own active profile, so a watch on any other
 * profile (including a freshly installed one) receives nothing. Sending it whenever the two
 * sides disagree keeps the watch fed without the user having to open the profile picker.
 */
suspend fun publishProfileBinding(context: Context, profileId: String) {
    withContext(Dispatchers.IO) {
        runCatching {
            val payload = profileId.toByteArray(Charsets.UTF_8)
            val nodes = Tasks.await(Wearable.getNodeClient(context).connectedNodes)
            Log.d("ProfileBind", "Publishing binding $profileId to ${nodes.size} node(s)")
            nodes.forEach { node ->
                runCatching {
                    Tasks.await(
                        Wearable.getMessageClient(context).sendMessage(
                            node.id,
                            DataLayerPaths.PROFILE_BIND_PREFIX,
                            payload,
                        )
                    )
                }
            }
        }.onFailure { Log.w("ProfileBind", "Could not publish binding for $profileId", it) }
    }
}

/**
 * Asks the phone to publish its profile list.
 *
 * A freshly installed watch knows nothing about profiles: without this it cannot decide which
 * profile to follow, and never announces itself, so the phone never sends anything.
 */
suspend fun requestProfileIndex(context: Context) {
    withContext(Dispatchers.IO) {
        runCatching {
            val nodes = Tasks.await(Wearable.getNodeClient(context).connectedNodes)
            Log.d("ProfileBind", "Requesting profile index from ${nodes.size} node(s)")
            nodes.forEach { node ->
                runCatching {
                    Tasks.await(
                        Wearable.getMessageClient(context).sendMessage(
                            node.id,
                            DataLayerPaths.PROFILE_REQUEST_PATH,
                            ByteArray(0),
                        )
                    )
                }
            }
        }.onFailure { Log.w("ProfileBind", "Could not request the profile index", it) }
    }
}
