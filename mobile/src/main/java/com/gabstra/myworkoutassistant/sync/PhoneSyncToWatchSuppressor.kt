package com.gabstra.myworkoutassistant.sync

import java.util.concurrent.atomic.AtomicInteger

/**
 * While depth > 0, [PhoneToWatchSyncCoordinator] must not schedule phone→Wear sync
 * (Wear-inbound persistence must not echo back to the watch).
 */
object PhoneSyncToWatchSuppressor {
    private val depth = AtomicInteger(0)

    fun enterWearInboundApply() {
        depth.incrementAndGet()
    }

    fun exitWearInboundApply() {
        depth.decrementAndGet()
    }

    fun shouldSuppressPhoneToWatchSync(): Boolean = depth.get() > 0
}
