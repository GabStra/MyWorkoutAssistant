package com.gabstra.myworkoutassistant.sync

import android.os.Handler
import android.os.Looper
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.util.Collections
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(manifest = Config.NONE, sdk = [35], application = android.app.Application::class)
class SyncRequestStartDeadlineTest {
    @Test
    fun duplicateRequestDoesNotExtendDeadline() {
        val expired = mutableListOf<String>()
        val deadline = deadline(expired)

        deadline.onRequest("tx")
        shadowOf(Looper.getMainLooper()).idleFor(10, TimeUnit.MILLISECONDS)
        deadline.onRequest("tx")
        shadowOf(Looper.getMainLooper()).idleFor(10, TimeUnit.MILLISECONDS)

        assertEquals(listOf("tx"), expired)
    }

    @Test
    fun backupStartCancelsPendingDeadline() {
        val expired = mutableListOf<String>()
        val deadline = deadline(expired)

        deadline.onRequest("tx")
        deadline.onBackupStarted()
        shadowOf(Looper.getMainLooper()).idleFor(10, TimeUnit.MILLISECONDS)

        assertEquals(emptyList<String>(), expired)
    }

    @Test
    fun staleCancellationLeavesNewerRequestPending() {
        val expired = mutableListOf<String>()
        val deadline = deadline(expired)

        deadline.onRequest("new")

        assertEquals(
            SyncRequestStartDeadline.Cancellation.DifferentPendingRequest("new"),
            deadline.cancel("old"),
        )
        shadowOf(Looper.getMainLooper()).idleFor(15, TimeUnit.MILLISECONDS)

        assertEquals(listOf("new"), expired)
    }

    @Test
    fun newerRequestReplacesOldDeadlineAndOldTimeoutCannotFire() {
        val expired = mutableListOf<String>()
        val deadline = deadline(expired)

        deadline.onRequest("old")
        shadowOf(Looper.getMainLooper()).idleFor(5, TimeUnit.MILLISECONDS)
        deadline.onRequest("new")
        shadowOf(Looper.getMainLooper()).idleFor(5, TimeUnit.MILLISECONDS)

        assertEquals(emptyList<String>(), expired)
        shadowOf(Looper.getMainLooper()).idleFor(5, TimeUnit.MILLISECONDS)
        assertEquals(emptyList<String>(), expired)
        shadowOf(Looper.getMainLooper()).idleFor(5, TimeUnit.MILLISECONDS)
        assertEquals(listOf("new"), expired)
    }

    @Test
    fun requestArrivingDuringExpiryCannotBeDismissedByOldTimeout() {
        var requestFinished: java.util.concurrent.CountDownLatch? = null
        var requestInterleavedWithTimeout = false
        val expired = mutableListOf<String>()
        lateinit var deadline: SyncRequestStartDeadline
        deadline = SyncRequestStartDeadline(
            handler = Handler(Looper.getMainLooper()),
            timeoutMillis = 10,
        ) { transactionId ->
            if (transactionId == "old") {
                val finished = java.util.concurrent.CountDownLatch(1)
                requestFinished = finished
                Thread {
                    deadline.onRequest("new")
                    finished.countDown()
                }.start()
                requestInterleavedWithTimeout = finished.await(50, TimeUnit.MILLISECONDS)
            }
            expired += transactionId
        }

        deadline.onRequest("old")
        shadowOf(Looper.getMainLooper()).idleFor(10, TimeUnit.MILLISECONDS)

        assertFalse(requestInterleavedWithTimeout)
        assertTrue(requestFinished?.await(1, TimeUnit.SECONDS) == true)
        shadowOf(Looper.getMainLooper()).idleFor(10, TimeUnit.MILLISECONDS)
        assertEquals(listOf("old", "new"), expired)
    }

    private fun deadline(expired: MutableList<String>) = SyncRequestStartDeadline(
        handler = Handler(Looper.getMainLooper()),
        timeoutMillis = 15,
        onTimeout = expired::add,
    )
}
