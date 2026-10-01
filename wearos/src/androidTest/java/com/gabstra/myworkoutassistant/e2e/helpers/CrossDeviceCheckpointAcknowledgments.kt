package com.gabstra.myworkoutassistant.e2e.helpers

import android.content.Context
import android.os.SystemClock
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.MessageClient
import com.google.android.gms.wearable.Wearable
import java.io.Closeable
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/** Test-only acknowledgments sent after the phone validates the persisted checkpoint. */
class CrossDeviceCheckpointAcknowledgments(context: Context) : Closeable {
    private val messageClient = Wearable.getMessageClient(context)
    private val observedCheckpoints = ConcurrentHashMap.newKeySet<String>()
    private val listener = MessageClient.OnMessageReceivedListener { event ->
        if (event.path == ACKNOWLEDGMENT_PATH) {
            observedCheckpoints.add(event.data.toString(Charsets.UTF_8))
        }
    }

    init {
        Tasks.await(messageClient.addListener(listener), 10, TimeUnit.SECONDS)
    }

    fun awaitCheckpoint(checkpoint: String, timeoutMs: Long = 45_000) {
        val deadline = SystemClock.elapsedRealtime() + timeoutMs
        while (SystemClock.elapsedRealtime() < deadline) {
            if (observedCheckpoints.remove(checkpoint)) return
            SystemClock.sleep(100)
        }
        error("Phone did not acknowledge persisted checkpoint '$checkpoint' within ${timeoutMs}ms")
    }

    override fun close() {
        Tasks.await(messageClient.removeListener(listener), 10, TimeUnit.SECONDS)
    }

    private companion object {
        const val ACKNOWLEDGMENT_PATH = "/e2e/workout-sync/checkpoint-observed"
    }
}
