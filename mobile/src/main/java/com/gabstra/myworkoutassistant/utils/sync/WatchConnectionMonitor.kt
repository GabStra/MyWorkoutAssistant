package com.gabstra.myworkoutassistant.utils.sync

import android.content.Context
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.google.android.gms.wearable.CapabilityClient
import com.google.android.gms.wearable.CapabilityInfo
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import com.google.android.gms.tasks.Tasks

/**
 * Event-driven watch availability. The watch advertises [DataLayerPaths.WEAR_APP_CAPABILITY]
 * (via android_wear_capabilities), so a CapabilityClient listener fires the moment it
 * becomes reachable/unreachable — consumers read [watchReachable] instead of polling
 * connectedNodes only when a sync is already triggered.
 */
object WatchConnectionMonitor {
    private val _watchReachable = MutableStateFlow(false)

    /** True when a Wear node advertising the sync capability is reachable. */
    val watchReachable: StateFlow<Boolean> = _watchReachable

    @Volatile
    private var installed = false

    /** False until the initial getCapability query resolved [watchReachable]. */
    @Volatile
    var isResolved = false
        private set

    fun install(context: Context) {
        if (installed) return
        installed = true
        val appContext = context.applicationContext
        val capabilityClient: CapabilityClient = Wearable.getCapabilityClient(appContext)

        capabilityClient.addListener(
            { info: CapabilityInfo ->
                isResolved = true
                _watchReachable.value = info.nodes.isNotEmpty()
            },
            DataLayerPaths.WEAR_APP_CAPABILITY,
        )
        CoroutineScope(SupervisorJob() + Dispatchers.IO).launch {
            _watchReachable.value = try {
                Tasks.await(
                    capabilityClient.getCapability(
                        DataLayerPaths.WEAR_APP_CAPABILITY,
                        CapabilityClient.FILTER_REACHABLE,
                    ),
                ).nodes.isNotEmpty()
            } catch (_: Exception) {
                false
            }
            isResolved = true
        }
    }
}
