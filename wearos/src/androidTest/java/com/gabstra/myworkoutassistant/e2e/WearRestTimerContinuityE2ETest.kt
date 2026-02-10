package com.gabstra.myworkoutassistant.e2e

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.uiautomator.By
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.driver.WearWorkoutDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.MultipleSetsAndRestsWorkoutStoreFixture
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import kotlin.math.ceil

@RunWith(AndroidJUnit4::class)
class WearRestTimerContinuityE2ETest : WearBaseE2ETest() {
    private lateinit var workoutDriver: WearWorkoutDriver

    @Before
    override fun baseSetUp() {
        super.baseSetUp()
        workoutDriver = createWorkoutDriver()
    }

    @Test
    fun restTimer_countsDownWithoutUnexpectedJumps() {
        MultipleSetsAndRestsWorkoutStoreFixture.setupWorkoutStore(context)
        launchAppFromHome()
        startWorkout(MultipleSetsAndRestsWorkoutStoreFixture.getWorkoutName())

        workoutDriver.completeCurrentSet()
        dismissTutorialIfPresent(TutorialContext.REST_SCREEN, 2_000)

        val restVisible = device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription)),
            5_000
        )
        require(restVisible) { "Rest screen did not appear" }

        val observations = mutableListOf<Pair<Long, Int>>()
        val deadline = System.currentTimeMillis() + 30_000

        while (System.currentTimeMillis() < deadline) {
            val seconds = readRestTimerSeconds()
            if (seconds != null) {
                val now = System.currentTimeMillis()
                val previous = observations.lastOrNull()
                if (previous == null || previous.second != seconds) {
                    observations += now to seconds
                }
            }
            device.waitForIdle(200)
        }

        require(observations.size >= 3) {
            "Insufficient timer samples captured on rest screen: ${observations.size}"
        }

        var sawDecrease = false
        observations.zipWithNext().forEach { (previous, current) ->
            val (previousAt, previousSeconds) = previous
            val (currentAt, currentSeconds) = current

            require(currentSeconds <= previousSeconds) {
                "Rest timer increased unexpectedly: $previousSeconds -> $currentSeconds"
            }

            if (currentSeconds < previousSeconds) {
                sawDecrease = true
            }

            val elapsedSeconds = (currentAt - previousAt) / 1000.0
            val observedDrop = previousSeconds - currentSeconds
            val allowedDrop = ceil(elapsedSeconds).toInt() + 1
            require(observedDrop <= allowedDrop) {
                "Rest timer jumped too much: $previousSeconds -> $currentSeconds in ${"%.2f".format(elapsedSeconds)}s"
            }
        }

        require(sawDecrease) { "Rest timer did not decrease during observation window" }
    }

    private fun readRestTimerSeconds(): Int? {
        val root = device.findObject(By.descContains(SetValueSemantics.RestSetTypeDescription)) ?: return null
        val timerText = findTimerText(root) ?: return null
        return parseTimerTextToSeconds(timerText)
    }

    private fun findTimerText(root: UiObject2): String? {
        val queue = ArrayDeque<UiObject2>()
        queue.add(root)

        while (queue.isNotEmpty()) {
            val current = queue.removeFirst()
            val text = runCatching { current.text }.getOrNull()
            if (!text.isNullOrBlank() && text.matches(Regex("\\d{2}:\\d{2}"))) {
                return text
            }

            val children = try {
                current.children
            } catch (_: StaleObjectException) {
                emptyList()
            }
            children.forEach(queue::addLast)
        }

        return null
    }

    private fun parseTimerTextToSeconds(timerText: String): Int {
        val parts = timerText.split(":")
        require(parts.size == 2) { "Unexpected rest timer format: $timerText" }

        val minutes = parts[0].toIntOrNull()
        val seconds = parts[1].toIntOrNull()
        require(minutes != null && seconds != null) { "Non-numeric rest timer format: $timerText" }

        return (minutes * 60) + seconds
    }
}

