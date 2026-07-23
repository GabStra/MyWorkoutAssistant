package com.gabstra.myworkoutassistant.e2e

import android.net.Uri
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.gabstra.myworkoutassistant.data.cleanupAbandonedWorkoutHistoryPayloadDataItems
import com.gabstra.myworkoutassistant.shared.datalayer.DataLayerPaths
import com.google.android.gms.tasks.Tasks
import com.google.android.gms.wearable.DataClient
import com.google.android.gms.wearable.PutDataMapRequest
import com.google.android.gms.wearable.Wearable
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

@RunWith(AndroidJUnit4::class)
class WearAbandonedWorkoutHistoryPayloadCleanupE2ETest : WearBaseE2ETest() {

    @Test
    fun cleanup_removesPayloadItemsButPreservesUnrelatedControlItem() = runBlocking {
        val dataClient = Wearable.getDataClient(context)
        val transactionId = "abandoned-${UUID.randomUUID()}"
        val startPath = DataLayerPaths.buildPath(
            DataLayerPaths.WORKOUT_HISTORY_START_PREFIX,
            transactionId
        )
        val chunkPath = DataLayerPaths.buildPath(
            DataLayerPaths.WORKOUT_HISTORY_CHUNK_PREFIX,
            transactionId,
            0
        )
        val controlPath = "/cleanupTest/control/$transactionId"

        try {
            putTestDataItem(dataClient, startPath)
            putTestDataItem(dataClient, chunkPath)
            putTestDataItem(dataClient, controlPath)

            cleanupAbandonedWorkoutHistoryPayloadDataItems(dataClient)

            assertEquals(0, countDataItems(dataClient, startPath))
            assertEquals(0, countDataItems(dataClient, chunkPath))
            assertTrue(countDataItems(dataClient, controlPath) > 0)
        } finally {
            deleteTestDataItems(dataClient, controlPath)
        }
    }

    private fun putTestDataItem(dataClient: DataClient, path: String) {
        val request = PutDataMapRequest.create(path).apply {
            dataMap.putString("testNonce", UUID.randomUUID().toString())
        }.asPutDataRequest().setUrgent()
        Tasks.await(dataClient.putDataItem(request))
    }

    private fun countDataItems(dataClient: DataClient, path: String): Int {
        val dataItems = Tasks.await(dataClient.dataItems)
        return try {
            dataItems.count { dataItem -> dataItem.uri.path == path }
        } finally {
            dataItems.release()
        }
    }

    private fun deleteTestDataItems(dataClient: DataClient, path: String) {
        Tasks.await(dataClient.deleteDataItems(wearUri(path), DataClient.FILTER_PREFIX))
    }

    private fun wearUri(path: String): Uri {
        return Uri.Builder()
            .scheme("wear")
            .path(path)
            .build()
    }
}
