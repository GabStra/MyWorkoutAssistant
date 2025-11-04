package com.gabstra.myworkoutassistant

import com.gabstra.myworkoutassistant.data.HrBpmSource
import com.gabstra.myworkoutassistant.data.ReconnectionActions
import com.gabstra.myworkoutassistant.data.StaleRetryingBpmStream
import io.reactivex.rxjava3.core.Completable
import io.reactivex.rxjava3.processors.PublishProcessor
import io.reactivex.rxjava3.schedulers.TestScheduler
import io.reactivex.rxjava3.subscribers.TestSubscriber
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.concurrent.TimeUnit

private class FakeHrBpmSource : HrBpmSource {
    var subscriptions = 0
    private var current: PublishProcessor<Int> = PublishProcessor.create()

    fun emit(v: Int) = current.onNext(v)

    override fun bpmStream(deviceId: String) = PublishProcessor
        .create<Int>()
        .also {
            subscriptions++
            current = it
        }
        .onBackpressureLatest()
}

private class FakeReconnector(private val delaySec: Long, private val scheduler: TestScheduler) :
    ReconnectionActions {
    var calls = 0
    override fun onStale(deviceId: String): Completable {
        calls++
        return Completable.complete() // reconnection itself is instant in this fake
    }
}

class StaleRetryingBpmStreamTest {

    @Test
    fun `stale timeout triggers reconnection and resubscription`() {
        val testScheduler = TestScheduler()
        val source = FakeHrBpmSource()
        val reconn = FakeReconnector(delaySec = 2, scheduler = testScheduler)

        val underTest = StaleRetryingBpmStream(
            deviceId = "12345678",
            source = source,
            reconnection = reconn,
            staleTimeoutSec = 15,
            backoffSec = 2,
            scheduler = testScheduler
        )

        val ts = TestSubscriber<Int>()
        underTest.stream().subscribe(ts)

        // first subscription created
        assertEquals(1, source.subscriptions)

        // Emit one value; no timeout yet
        source.emit(70)
        ts.assertValues(70)

        // Advance less than timeout → no reconnection
        testScheduler.advanceTimeBy(10, TimeUnit.SECONDS)
        assertEquals(0, reconn.calls)
        assertEquals(1, source.subscriptions)

        // Now go past the 15s timeout → TimeoutException → reconnection + backoff(2s) → resubscribe
        testScheduler.advanceTimeBy(6, TimeUnit.SECONDS) // reaches 16s total since last item
        // retryWhen waits for backoff timer to fire; advance 2s for backoff
        testScheduler.advanceTimeBy(2, TimeUnit.SECONDS)

        assertEquals(1, reconn.calls)
        assertEquals(2, source.subscriptions) // resubscribed

        // After resubscribe, new values flow
        source.emit(72)
        ts.assertValues(70, 72)
        ts.assertNotComplete()
        ts.assertNoErrors()
    }
}