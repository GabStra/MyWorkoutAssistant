package com.gabstra.myworkoutassistant.benchmark

import android.os.SystemClock
import android.os.Bundle
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings
import com.gabstra.myworkoutassistant.e2e.WearBaseE2ETest
import java.io.FileInputStream
import java.util.Locale
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PageExercisesScrollBenchmark : WearBaseE2ETest() {
    private val measuredIterations = 5
    private val maxScrollSwipes = 80
    private val bottomRowLabel = PageExercisesScrollBenchmarkFixture.ROW_COUNT.toString()

    override fun prepareAppStateBeforeLaunch() {
        PageExercisesScrollBenchmarkFixture.setupWorkoutStore(context)
    }

    @Test
    fun pageExercisesScrollToBottomBenchmark() {
        val workoutDriver = createWorkoutDriver()
        startWorkout(PageExercisesScrollBenchmarkFixture.WORKOUT_NAME)

        val onExercisesPage = workoutDriver.navigateToExercisesPage()
        require(onExercisesPage) { "Exercises page did not become visible for benchmark" }

        require(waitForRowSettled("1")) { "Top PageExercises row was not visible before benchmark" }

        scrollToRowSettled(bottomRowLabel, ScrollGesture.UP)
        scrollToRowSettled("1", ScrollGesture.DOWN)

        val measurements = mutableListOf<PageExercisesScrollMeasurement>()

        resetFrameStats()
        repeat(measuredIterations) {
            scrollToRowSettled("1", ScrollGesture.DOWN)
            require(isRowVisible("1")) { "Top PageExercises row was not visible before measured iteration ${it + 1}" }
            measurements += measureScrollToRow(bottomRowLabel)
        }
        val frameStats = collectFrameStats()

        val totalMs = measurements.map { it.totalMs }
        val scrollMs = measurements.map { it.scrollMs }
        val swipes = measurements.map { it.swipes }
        val scrollMsPerSwipe = measurements.map { it.scrollMs.toDouble() / it.swipes }
        val totalMsPerSwipe = measurements.map { it.totalMs.toDouble() / it.swipes }
        val result = PageExercisesScrollBenchmarkResult(
            rows = PageExercisesScrollBenchmarkFixture.ROW_COUNT,
            iterations = measuredIterations,
            scrollMs = scrollMs,
            medianScrollMs = scrollMs.median(),
            minScrollMs = scrollMs.minOrNull() ?: 0L,
            maxScrollMs = scrollMs.maxOrNull() ?: 0L,
            totalMs = totalMs,
            medianTotalMs = totalMs.median(),
            swipes = swipes,
            scrollMsPerSwipe = scrollMsPerSwipe,
            medianScrollMsPerSwipe = scrollMsPerSwipe.median(),
            totalMsPerSwipe = totalMsPerSwipe,
            medianTotalMsPerSwipe = totalMsPerSwipe.median(),
            gestureMs = measurements.map { it.gestureMs },
            rowLookupMs = measurements.map { it.rowLookupMs },
            idleWaitMs = measurements.map { it.idleWaitMs },
            frameStats = frameStats
        )
        emitBenchmarkMetric("BENCHMARK_METRIC PageExercisesScroll ${result.toJson()}")
    }

    private fun emitBenchmarkMetric(metricLine: String) {
        println(metricLine)
        InstrumentationRegistry.getInstrumentation().sendStatus(
            0,
            Bundle().apply {
                putString("benchmark_metric", metricLine)
            }
        )
    }

    private fun scrollToRowSettled(label: String, gesture: ScrollGesture): Int {
        if (waitForRowSettled(label, timeoutMs = E2ETestTimings.SHORT_IDLE_MS)) {
            return 0
        }

        repeat(maxScrollSwipes) { index ->
            performVerticalGesture(gesture = gesture, waitForIdle = true)
            if (waitForRowSettled(label, timeoutMs = E2ETestTimings.SHORT_IDLE_MS)) {
                return index + 1
            }
        }

        error("Row '$label' was not visible after $maxScrollSwipes ${gesture.name.lowercase()} swipes")
    }

    private fun measureScrollToRow(label: String): PageExercisesScrollMeasurement {
        val startedAt = SystemClock.elapsedRealtime()
        var gestureMs = 0L
        var rowLookupMs = 0L
        var idleWaitMs = 0L

        repeat(maxScrollSwipes) { index ->
            val swipeStartedAt = SystemClock.elapsedRealtime()
            performVerticalGesture(gesture = ScrollGesture.UP, waitForIdle = false)
            gestureMs += SystemClock.elapsedRealtime() - swipeStartedAt

            val idleStartedAt = SystemClock.elapsedRealtime()
            device.waitForIdle(16)
            idleWaitMs += SystemClock.elapsedRealtime() - idleStartedAt

            val lookupStartedAt = SystemClock.elapsedRealtime()
            val rowVisible = isRowVisible(label)
            rowLookupMs += SystemClock.elapsedRealtime() - lookupStartedAt

            if (rowVisible) {
                return PageExercisesScrollMeasurement(
                    totalMs = SystemClock.elapsedRealtime() - startedAt,
                    swipes = index + 1,
                    gestureMs = gestureMs,
                    rowLookupMs = rowLookupMs,
                    idleWaitMs = idleWaitMs
                )
            }
        }

        error("Row '$label' was not visible after $maxScrollSwipes measured swipes")
    }

    private fun waitForRowSettled(label: String, timeoutMs: Long = 1_000): Boolean {
        return device.wait(Until.hasObject(By.desc(label)), timeoutMs)
    }

    private fun isRowVisible(label: String): Boolean {
        return device.hasObject(By.desc(label))
    }

    private fun performVerticalGesture(gesture: ScrollGesture, waitForIdle: Boolean) {
        val width = device.displayWidth
        val height = device.displayHeight
        val centerX = width / 2
        val topY = (height * 0.28f).toInt().coerceAtLeast(1)
        val bottomY = (height * 0.72f).toInt().coerceAtMost(height - 1)

        when (gesture) {
            ScrollGesture.UP -> device.swipe(centerX, bottomY, centerX, topY, 8)
            ScrollGesture.DOWN -> device.swipe(centerX, topY, centerX, bottomY, 8)
        }
        if (waitForIdle) {
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
    }

    private fun resetFrameStats() {
        runShellCommand("dumpsys gfxinfo ${context.packageName} reset")
    }

    private fun collectFrameStats(): PageExercisesFrameStats? {
        val output = runShellCommand("dumpsys gfxinfo ${context.packageName}")
        return PageExercisesFrameStats.fromGfxInfo(output)
    }

    private fun runShellCommand(command: String): String {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val descriptor = instrumentation.uiAutomation.executeShellCommand(command)
        return FileInputStream(descriptor.fileDescriptor).bufferedReader().use { reader ->
            reader.readText()
        }.also {
            descriptor.close()
        }
    }

    private enum class ScrollGesture {
        UP,
        DOWN
    }
}

private data class PageExercisesScrollMeasurement(
    val totalMs: Long,
    val swipes: Int,
    val gestureMs: Long,
    val rowLookupMs: Long,
    val idleWaitMs: Long
) {
    val scrollMs: Long = (totalMs - rowLookupMs).coerceAtLeast(0L)
}

private data class PageExercisesScrollBenchmarkResult(
    val rows: Int,
    val iterations: Int,
    val scrollMs: List<Long>,
    val medianScrollMs: Long,
    val minScrollMs: Long,
    val maxScrollMs: Long,
    val totalMs: List<Long>,
    val medianTotalMs: Long,
    val swipes: List<Int>,
    val scrollMsPerSwipe: List<Double>,
    val medianScrollMsPerSwipe: Double,
    val totalMsPerSwipe: List<Double>,
    val medianTotalMsPerSwipe: Double,
    val gestureMs: List<Long>,
    val rowLookupMs: List<Long>,
    val idleWaitMs: List<Long>,
    val frameStats: PageExercisesFrameStats?
) {
    fun toJson(): String {
        return buildString {
            append("{")
            append("\"rows\":").append(rows).append(",")
            append("\"iterations\":").append(iterations).append(",")
            append("\"scrollMs\":").append(scrollMs.joinToString(prefix = "[", postfix = "]")).append(",")
            append("\"medianScrollMs\":").append(medianScrollMs).append(",")
            append("\"minScrollMs\":").append(minScrollMs).append(",")
            append("\"maxScrollMs\":").append(maxScrollMs).append(",")
            append("\"totalMs\":").append(totalMs.joinToString(prefix = "[", postfix = "]")).append(",")
            append("\"medianTotalMs\":").append(medianTotalMs).append(",")
            append("\"swipes\":").append(swipes.joinToString(prefix = "[", postfix = "]")).append(",")
            append("\"scrollMsPerSwipe\":").append(scrollMsPerSwipe.toJsonArray()).append(",")
            append("\"medianScrollMsPerSwipe\":").append(medianScrollMsPerSwipe.toJsonNumber()).append(",")
            append("\"totalMsPerSwipe\":").append(totalMsPerSwipe.toJsonArray()).append(",")
            append("\"medianTotalMsPerSwipe\":").append(medianTotalMsPerSwipe.toJsonNumber()).append(",")
            append("\"gestureMs\":").append(gestureMs.joinToString(prefix = "[", postfix = "]")).append(",")
            append("\"rowLookupMs\":").append(rowLookupMs.joinToString(prefix = "[", postfix = "]")).append(",")
            append("\"idleWaitMs\":").append(idleWaitMs.joinToString(prefix = "[", postfix = "]")).append(",")
            append("\"frameStats\":").append(frameStats?.toJson() ?: "null")
            append("}")
        }
    }
}

private data class PageExercisesFrameStats(
    val totalFrames: Int?,
    val jankyFrames: Int?,
    val jankyFramePercent: Double?,
    val percentile50Ms: Int?,
    val percentile90Ms: Int?,
    val percentile95Ms: Int?,
    val percentile99Ms: Int?,
) {
    fun toJson(): String {
        return buildString {
            append("{")
            append("\"totalFrames\":").append(totalFrames?.toString() ?: "null").append(",")
            append("\"jankyFrames\":").append(jankyFrames?.toString() ?: "null").append(",")
            append("\"jankyFramePercent\":").append(jankyFramePercent?.toJsonNumber() ?: "null").append(",")
            append("\"percentile50Ms\":").append(percentile50Ms?.toString() ?: "null").append(",")
            append("\"percentile90Ms\":").append(percentile90Ms?.toString() ?: "null").append(",")
            append("\"percentile95Ms\":").append(percentile95Ms?.toString() ?: "null").append(",")
            append("\"percentile99Ms\":").append(percentile99Ms?.toString() ?: "null")
            append("}")
        }
    }

    companion object {
        fun fromGfxInfo(output: String): PageExercisesFrameStats? {
            val totalFrames = output.findInt("Total frames rendered:\\s*(\\d+)")
            val jankyMatch = Regex("Janky frames:\\s*(\\d+)\\s*\\(([^%]+)%\\)").find(output)
            val jankyFrames = jankyMatch?.groupValues?.getOrNull(1)?.toIntOrNull()
            val jankyPercent = jankyMatch?.groupValues?.getOrNull(2)?.trim()?.toDoubleOrNull()
            val stats = PageExercisesFrameStats(
                totalFrames = totalFrames,
                jankyFrames = jankyFrames,
                jankyFramePercent = jankyPercent,
                percentile50Ms = output.findInt("50th percentile:\\s*(\\d+)ms"),
                percentile90Ms = output.findInt("90th percentile:\\s*(\\d+)ms"),
                percentile95Ms = output.findInt("95th percentile:\\s*(\\d+)ms"),
                percentile99Ms = output.findInt("99th percentile:\\s*(\\d+)ms")
            )
            return if (stats.hasAnyValue()) stats else null
        }

        private fun String.findInt(pattern: String): Int? {
            return Regex(pattern).find(this)?.groupValues?.getOrNull(1)?.toIntOrNull()
        }
    }

    private fun hasAnyValue(): Boolean {
        return totalFrames != null ||
            jankyFrames != null ||
            jankyFramePercent != null ||
            percentile50Ms != null ||
            percentile90Ms != null ||
            percentile95Ms != null ||
            percentile99Ms != null
    }
}

private fun List<Long>.median(): Long {
    if (isEmpty()) return 0L
    val sorted = sorted()
    val middle = sorted.size / 2
    return if (sorted.size % 2 == 1) {
        sorted[middle]
    } else {
        (sorted[middle - 1] + sorted[middle]) / 2
    }
}

private fun List<Double>.median(): Double {
    if (isEmpty()) return 0.0
    val sorted = sorted()
    val middle = sorted.size / 2
    return if (sorted.size % 2 == 1) {
        sorted[middle]
    } else {
        (sorted[middle - 1] + sorted[middle]) / 2.0
    }
}

private fun List<Double>.toJsonArray(): String {
    return joinToString(prefix = "[", postfix = "]") { value -> value.toJsonNumber() }
}

private fun Double.toJsonNumber(): String {
    return String.format(Locale.US, "%.3f", this)
}
