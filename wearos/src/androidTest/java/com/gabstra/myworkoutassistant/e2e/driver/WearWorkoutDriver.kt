package com.gabstra.myworkoutassistant.e2e.driver

import android.content.Intent
import androidx.test.platform.app.InstrumentationRegistry
import android.content.Context
import androidx.test.uiautomator.By
import androidx.test.uiautomator.Direction
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.BySelector
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until
import com.gabstra.myworkoutassistant.composables.SetValueSemantics
import com.gabstra.myworkoutassistant.e2e.E2ETestTimings

/**
 * Reusable UI driver for common workout E2E interactions.
 * Keeps interaction patterns in one place so tests remain scenario-focused.
 */
class WearWorkoutDriver(
    private val device: UiDevice,
    private val longPressByDesc: (String, Long) -> Unit
) {
    data class RecoveryResumeResult(
        val enteredWorkout: Boolean,
        val resumeActionAtMs: Long?,
        val enteredWorkoutAtMs: Long?
    )

    data class TimedDurationReadResult(
        val seconds: Int,
        val readAtMs: Long
    )

    data class ProcessKillResult(
        val homePressedAtMs: Long,
        val killIssuedAtMs: Long
    )

    fun clickObjectOrAncestor(obj: UiObject2) {
        clickObjectOrAncestorInternal(obj)
    }

    fun waitForText(text: String, timeoutMs: Long): Boolean {
        return device.wait(Until.hasObject(By.text(text)), timeoutMs)
    }

    fun clickText(text: String, timeoutMs: Long) {
        val obj = device.wait(Until.findObject(By.text(text)), timeoutMs)
        require(obj != null) {
            "Timed out waiting for UI object with text '$text' to appear"
        }
        clickObjectOrAncestorInternal(obj)
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
    }

    fun clickLabel(label: String, timeoutMs: Long) {
        val obj = device.wait(Until.findObject(By.desc(label)), timeoutMs)
            ?: device.wait(Until.findObject(By.text(label)), timeoutMs)
        require(obj != null) {
            "Timed out waiting for UI object with label '$label' to appear"
        }
        clickObjectOrAncestorInternal(obj)
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
    }

    fun scrollUntilFound(
        selector: BySelector,
        direction: Direction,
        initialWaitMs: Long = 1_000
    ): UiObject2? {
        device.wait(Until.findObject(selector), initialWaitMs)?.let { return it }

        val scrollable = device.findObject(By.scrollable(true))
        if (scrollable != null) {
            return runCatching {
                scrollable.scrollUntil(direction, Until.findObject(selector))
            }.getOrNull()
        }

        return null
    }

    fun navigateToPagerPage(direction: Direction) {
        val width = device.displayWidth
        val height = device.displayHeight
        val swipeY = (height * 0.20).toInt().coerceAtLeast(1)

        if (direction == Direction.LEFT) {
            val startX = (width * 0.8).toInt().coerceAtMost(width - 1)
            val endX = (width * 0.2).toInt().coerceAtLeast(0)
            device.swipe(startX, swipeY, endX, swipeY, 5)
        } else {
            val startX = (width * 0.2).toInt().coerceAtLeast(0)
            val endX = (width * 0.8).toInt().coerceAtMost(width - 1)
            device.swipe(startX, swipeY, endX, swipeY, 5)
        }
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
    }

    fun dismissResumeDialogIfPresent(timeoutMs: Long = 2_000) {
        val resumeVisible = device.wait(Until.hasObject(By.textContains("Resume")), timeoutMs)
        if (resumeVisible) {
            device.pressBack()
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }
    }

    fun openWorkoutDetailAndStartOrResume(
        workoutName: String,
        timeoutMs: Long
    ): String {
        val openWorkoutDesc = "Open workout: $workoutName"
        val detailDesc = "Workout detail: $workoutName"
        val openWorkout = device.wait(Until.findObject(By.desc(openWorkoutDesc)), 2_000)
            ?: device.wait(Until.findObject(By.text(workoutName)), 2_000)
        require(openWorkout != null) { "Workout '$workoutName' not visible to tap" }
        clickObjectOrAncestorInternal(openWorkout)
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)

        val detailAppeared =
            device.wait(Until.hasObject(By.desc(detailDesc)), timeoutMs) ||
                device.wait(Until.hasObject(By.text(workoutName)), timeoutMs)
        require(detailAppeared) { "Workout detail with '$workoutName' not visible" }

        val action = findWorkoutDetailPrimaryAction()
            ?: error("Neither 'Start' nor 'Resume' is visible for workout '$workoutName'")
        clickObjectOrAncestorInternal(action.second)
        return action.first
    }

    fun killAppProcess(packageName: String, settleMs: Long = 1_000) {
        killAppProcessTimed(packageName = packageName, settleMs = settleMs)
    }

    fun killAppProcessTimed(packageName: String, settleMs: Long = 1_000): ProcessKillResult {
        // Move app to background first so pause/stop persistence hooks run.
        val homePressedAtMs = System.currentTimeMillis()
        device.pressHome()
        if (settleMs > 0) {
            device.waitForIdle(settleMs)
        }
        val killIssuedAtMs = System.currentTimeMillis()
        device.executeShellCommand("am kill $packageName")
        if (settleMs > 0) {
            device.waitForIdle(settleMs)
        }
        return ProcessKillResult(
            homePressedAtMs = homePressedAtMs,
            killIssuedAtMs = killIssuedAtMs
        )
    }

    fun readTimedDurationSeconds(
        perAttemptTimeoutMs: Long = 2_000,
        attempts: Int = 5
    ): Int {
        return readTimedDurationSecondsTimed(
            perAttemptTimeoutMs = perAttemptTimeoutMs,
            attempts = attempts,
            idleBetweenAttempts = true,
            requireTimerSemantics = false
        ).seconds
    }

    fun readTimedDurationSecondsTimed(
        perAttemptTimeoutMs: Long = 2_000,
        attempts: Int = 5,
        idleBetweenAttempts: Boolean = false,
        requireTimerSemantics: Boolean = false
    ): TimedDurationReadResult {
        repeat(attempts) {
            val timerRoot = device.wait(
                Until.findObject(By.descContains(SetValueSemantics.TimedDurationValueDescription)),
                perAttemptTimeoutMs
            )
            val timerText = timerRoot?.let { findTimerText(it) }
                ?: if (!requireTimerSemantics) {
                    device.findObjects(By.textContains(":"))
                        .mapNotNull { node -> runCatching { node.text }.getOrNull() }
                        .firstOrNull { it.matches(Regex("\\d{2}:\\d{2}(?::\\d{2})?")) }
                } else {
                    null
                }

            if (!timerText.isNullOrBlank()) {
                return TimedDurationReadResult(
                    seconds = parseTimerTextToSeconds(timerText),
                    readAtMs = System.currentTimeMillis()
                )
            }
            if (idleBetweenAttempts) {
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            }
        }

        error("Could not read timed duration value from UI")
    }

    fun completeCurrentSet(timeoutMs: Long = 5_000) {
        device.pressBack()
        if (tryConfirmLongPressDialog(timeoutMs)) return

        // Some UI layers (e.g., inline editors/overlays) consume the first back press.
        device.pressBack()
        val confirmed = tryConfirmLongPressDialog(timeoutMs)
        require(confirmed) { "Timed out waiting for set confirmation dialog ('Done')" }
    }

    fun confirmLongPressDialog(timeoutMs: Long = 5_000) {
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        longPressByDesc("Done", timeoutMs)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }

    private fun tryConfirmLongPressDialog(timeoutMs: Long): Boolean {
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        val hasDone = device.wait(Until.hasObject(By.desc("Done")), timeoutMs)
        if (!hasDone) return false
        longPressByDesc("Done", timeoutMs)
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        return true
    }

    fun skipRest(timeoutMs: Long = 3_000) {
        device.pressBack()
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        device.pressBack()
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)

        val dialogAppeared = device.wait(Until.hasObject(By.text("Skip Rest")), timeoutMs)
        require(dialogAppeared) { "Skip Rest dialog did not appear" }
        longPressByDesc("Done", timeoutMs)
    }

    fun waitForWorkoutCompletion(timeoutMs: Long = 10_000) {
        val deadline = System.currentTimeMillis() + timeoutMs
        var completedVisible = false
        while (System.currentTimeMillis() < deadline && !completedVisible) {
            completedVisible =
                device.hasObject(By.text("Completed")) ||
                    device.hasObject(By.text("COMPLETED")) ||
                    device.hasObject(By.text("Workout completed"))
            if (!completedVisible) {
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            }
        }
        require(completedVisible) { "Workout completion screen did not appear" }
    }

    fun resumeOrEnterRecoveredWorkout(
        workoutName: String,
        inWorkoutSelector: BySelector,
        timeoutMs: Long = 10_000
    ): Boolean {
        return resumeOrEnterRecoveredWorkoutTimed(
            workoutName = workoutName,
            inWorkoutSelector = inWorkoutSelector,
            timeoutMs = timeoutMs
        ).enteredWorkout
    }

    fun resumeOrEnterRecoveredWorkoutTimed(
        workoutName: String,
        inWorkoutSelector: BySelector,
        timeoutMs: Long = 10_000
    ): RecoveryResumeResult {
        if (isLikelyInActiveWorkout(inWorkoutSelector)) {
            return RecoveryResumeResult(true, null, System.currentTimeMillis())
        }

        var resumeActionAtMs: Long? = null
        var enteredWorkoutAtMs: Long? = null
        val deadline = System.currentTimeMillis() + timeoutMs
        var workoutEntryOpened = false

        while (System.currentTimeMillis() < deadline) {
            if (isLikelyInActiveWorkout(inWorkoutSelector)) {
                enteredWorkoutAtMs = System.currentTimeMillis()
                break
            }

            clickContinueTimerIfVisible()
            clickContinueCalibrationIfVisible()
            val resumeButton = findResumeButton()
            if (resumeButton != null) {
                clickObjectOrAncestorInternal(resumeButton)
                resumeActionAtMs = System.currentTimeMillis()
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                if (waitForActiveWorkoutEntry(inWorkoutSelector, 1_500)) {
                    enteredWorkoutAtMs = System.currentTimeMillis()
                    break
                }
            } else if (!workoutEntryOpened) {
                val workoutEntry = device.findObject(By.desc("Open workout: $workoutName"))
                    ?: device.findObject(By.text(workoutName))
                if (workoutEntry != null) {
                    clickObjectOrAncestorInternal(workoutEntry)
                    workoutEntryOpened = true
                    device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                }
            } else {
                scrollRecoveryDialogDown()
            }

            Thread.sleep(100)
        }

        val entered = enteredWorkoutAtMs != null
        return RecoveryResumeResult(
            enteredWorkout = entered,
            resumeActionAtMs = resumeActionAtMs,
            enteredWorkoutAtMs = enteredWorkoutAtMs
        )
    }

    private fun findResumeButton(): UiObject2? {
        val directMatch = device.findObject(By.desc("Recovery resume action"))
            ?: device.findObject(By.text("Resume"))
            ?: device.findObject(By.textContains("Resume"))
            ?: device.findObject(By.desc("Resume workout"))
            ?: device.findObject(By.descContains("Resume"))
        if (directMatch != null) return directMatch

        return device.findObjects(By.clickable(true)).firstOrNull { obj ->
            val text = runCatching { obj.text }.getOrNull().orEmpty()
            val desc = runCatching { obj.contentDescription }.getOrNull().orEmpty()
            text.contains("resume", ignoreCase = true) ||
                desc.contains("resume", ignoreCase = true)
        }
    }

    private fun clickContinueTimerIfVisible() {
        val continueTimerButton = device.findObject(By.desc("Recovery timer continue option"))
            ?: device.findObject(By.textContains("Continue timer"))
            ?: device.findObjects(By.clickable(true)).firstOrNull { obj ->
                val text = runCatching { obj.text }.getOrNull().orEmpty()
                val desc = runCatching { obj.contentDescription }.getOrNull().orEmpty()
                text.contains("continue timer", ignoreCase = true) ||
                    desc.contains("continue timer", ignoreCase = true)
            }

        if (continueTimerButton != null) {
            clickObjectOrAncestorInternal(continueTimerButton)
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
    }

    private fun clickContinueCalibrationIfVisible() {
        val continueCalibrationButton = device.findObject(By.desc("Recovery calibration continue option"))
            ?: device.findObject(By.textContains("Continue calibration"))
            ?: device.findObjects(By.clickable(true)).firstOrNull { obj ->
                val text = runCatching { obj.text }.getOrNull().orEmpty()
                val desc = runCatching { obj.contentDescription }.getOrNull().orEmpty()
                text.contains("continue calibration", ignoreCase = true) ||
                    desc.contains("continue calibration", ignoreCase = true)
            }

        if (continueCalibrationButton != null) {
            clickObjectOrAncestorInternal(continueCalibrationButton)
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
    }

    private fun scrollRecoveryDialogDown() {
        val scrollable = device.findObject(By.scrollable(true))
        if (scrollable != null) {
            runCatching { scrollable.scroll(Direction.DOWN, 0.75f) }
        } else {
            verticalSwipe(Direction.DOWN)
        }
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
    }

    private fun waitForActiveWorkoutEntry(inWorkoutSelector: BySelector, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (isLikelyInActiveWorkout(inWorkoutSelector)) {
                return true
            }
            Thread.sleep(100)
        }
        return false
    }

    private fun isLikelyInActiveWorkout(inWorkoutSelector: BySelector): Boolean {
        return device.hasObject(inWorkoutSelector) ||
            device.hasObject(By.descContains(SetValueSemantics.TimedDurationValueDescription)) ||
            device.hasObject(By.text("Stop")) ||
            device.hasObject(By.desc("Stop"))
    }

    /**
     * Completes a timed/endurance set:
     * - manual sets: Start -> short wait -> Stop
     * - auto-start sets: short passive wait
     * Then completes the set confirmation dialog.
     */
    fun completeTimedSet(timeoutMs: Long = 5_000) {
        val started = clickButtonWithRetry("Start", timeoutMs = 3_000, attempts = 4)
        if (started) {
            waitForControl("Stop", timeoutMs = 4_000)
            clickButtonWithRetry("Stop", timeoutMs = 2_000, attempts = 3)
        } else {
            // Auto-start sets begin after countdown; continue as soon as Stop or Done is visible.
            waitForAnyControl(timeoutMs = 4_000, labels = arrayOf("Stop", "Done"))
        }

        completeCurrentSet(timeoutMs)
    }

    fun goHomeAndVerifySelection(timeoutMs: Long = 5_000) {
        val goHomeSelector = By.text("Go Home")
        val backSelector = By.text("Back")

        fun findGoHomeWithVerticalScroll(): UiObject2? {
            device.wait(Until.findObject(goHomeSelector), 500)?.let { return it }
            val scrollable = device.findObject(By.scrollable(true)) ?: return null
            return runCatching {
                scrollable.scrollUntil(Direction.DOWN, Until.findObject(goHomeSelector))
            }.getOrNull()
        }

        fun swipeUpOnce() {
            val width = device.displayWidth
            val height = device.displayHeight
            val centerX = width / 2
            val startY = (height * 0.75).toInt()
            val endY = (height * 0.30).toInt()
            device.swipe(centerX, startY, centerX, endY, 10)
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }

        var goHome: UiObject2? = findGoHomeWithVerticalScroll()

        if (goHome == null) {
            // Deterministic first move: Buttons page is typically one swipe RIGHT from default page.
            repeat(2) {
                val width = device.displayWidth
                val swipeY = (device.displayHeight * 0.20).toInt().coerceAtLeast(1)
                device.swipe(
                    (width * 0.2).toInt().coerceAtLeast(0),
                    swipeY,
                    (width * 0.8).toInt().coerceAtMost(width - 1),
                    swipeY,
                    6
                )
                device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                goHome = findGoHomeWithVerticalScroll()
                if (goHome != null) return@repeat
            }
        }

        if (goHome == null) {
            // On Rest/Exercise screens the Buttons page is often one swipe RIGHT from default page.
            repeat(4) {
                if (device.wait(Until.hasObject(backSelector), 400)) {
                    goHome = findGoHomeWithVerticalScroll()
                    if (goHome != null) return@repeat
                }
                val width = device.displayWidth
                val swipeY = (device.displayHeight * 0.20).toInt().coerceAtLeast(1)
                device.swipe(
                    (width * 0.2).toInt().coerceAtLeast(0),
                    swipeY,
                    (width * 0.8).toInt().coerceAtMost(width - 1),
                    swipeY,
                    6
                )
                device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                goHome = findGoHomeWithVerticalScroll()
                if (goHome != null) return@repeat
            }
        }

        if (goHome == null) {
            // Fallback scan in opposite direction in case pager position differs.
            repeat(4) {
                val width = device.displayWidth
                val swipeY = (device.displayHeight * 0.20).toInt().coerceAtLeast(1)
                device.swipe(
                    (width * 0.8).toInt().coerceAtMost(width - 1),
                    swipeY,
                    (width * 0.2).toInt().coerceAtLeast(0),
                    swipeY,
                    6
                )
                device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
                goHome = findGoHomeWithVerticalScroll()
                if (goHome != null) return@repeat
            }
        }

        if (goHome == null) {
            // Final attempt: force vertical swipes in case TransformingLazyColumn is not exposed as scrollable.
            repeat(6) {
                goHome = device.wait(Until.findObject(goHomeSelector), 500)
                if (goHome != null) return@repeat
                swipeUpOnce()
            }
        }

        if (goHome != null) {
            goHome.click()
            device.waitForIdle(E2ETestTimings.LONG_IDLE_MS)
        } else {
            // Fallback for flows where Buttons page is unavailable: relaunch app to selection screen.
            val targetContext = InstrumentationRegistry.getInstrumentation().targetContext
            val launchIntent = targetContext.packageManager
                .getLaunchIntentForPackage(targetContext.packageName)
                ?.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TASK or Intent.FLAG_ACTIVITY_NEW_TASK)
            require(launchIntent != null) { "Go Home button not found after scrolling" }
            device.pressHome()
            targetContext.startActivity(launchIntent)
            device.wait(Until.hasObject(By.pkg(targetContext.packageName).depth(0)), timeoutMs)
        }

        val headerVisible = device.wait(Until.hasObject(By.text("My Workout Assistant")), timeoutMs)
        require(headerVisible) { "Did not return to WorkoutSelectionScreen after Go Home/relaunch" }
    }

    fun waitForSyncedIds(
        context: Context,
        timeoutMs: Long,
        prefsName: String = "synced_workout_history_ids",
        key: String = "ids"
    ): Boolean {
        val prefs = context.getSharedPreferences(prefsName, Context.MODE_PRIVATE)
        val deadline = System.currentTimeMillis() + timeoutMs

        while (System.currentTimeMillis() < deadline) {
            if (prefs.getStringSet(key, emptySet()).orEmpty().isNotEmpty()) {
                return true
            }
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }

        return false
    }

    private fun waitForButtonByLabel(label: String, timeoutMs: Long = 2_000): UiObject2? {
        return device.wait(Until.findObject(By.desc(label)), timeoutMs)
            ?: device.wait(Until.findObject(By.text(label)), timeoutMs)
    }

    private fun clickButtonWithRetry(
        label: String,
        timeoutMs: Long = 2_000,
        attempts: Int = 3
    ): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        repeat(attempts) {
            val remaining = deadline - System.currentTimeMillis()
            if (remaining <= 0L) {
                return false
            }

            val stepTimeout = if (remaining > 1_000L) 1_000L else remaining
            val button = waitForButtonByLabel(label, stepTimeout)
            if (button != null && clickBestEffort(button)) {
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    private fun waitForControl(label: String, timeoutMs: Long): Boolean {
        return waitForAnyControl(timeoutMs = timeoutMs, labels = arrayOf(label))
    }

    private fun waitForAnyControl(timeoutMs: Long, labels: Array<String>): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (labels.any { label ->
                    device.findObject(By.desc(label)) != null || device.findObject(By.text(label)) != null
                }) {
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    private fun findWorkoutDetailPrimaryAction(): Pair<String, UiObject2>? {
        fun findVisibleAction(): Pair<String, UiObject2>? {
            val startButton = device.findObject(By.desc("Start workout"))
                ?: device.findObject(By.text("Start"))
                ?: device.findObject(By.desc("Start"))
            if (startButton != null) return "start" to startButton

            val resumeButton = device.findObject(By.desc("Resume workout"))
                ?: device.findObject(By.textContains("Resume"))
                ?: device.findObject(By.descContains("Resume"))
            if (resumeButton != null) return "resume" to resumeButton

            return null
        }

        findVisibleAction()?.let { return it }

        val scrollable = device.findObject(By.scrollable(true))
        if (scrollable != null) {
            runCatching { scrollable.scroll(Direction.DOWN, 0.75f) }
        } else {
            verticalSwipe(Direction.DOWN)
        }
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)

        return findVisibleAction()
    }

    private fun verticalSwipe(direction: Direction) {
        val width = device.displayWidth
        val height = device.displayHeight
        val centerX = width / 2
        val topY = (height * 0.25).toInt().coerceAtLeast(1)
        val bottomY = (height * 0.75).toInt().coerceAtMost(height - 1)
        if (direction == Direction.DOWN) {
            device.swipe(centerX, bottomY, centerX, topY, 8)
        } else {
            device.swipe(centerX, topY, centerX, bottomY, 8)
        }
    }

    private fun clickObjectOrAncestorInternal(obj: UiObject2) {
        var current: UiObject2? = obj
        while (current != null && !current.isClickable) {
            current = current.parent
        }
        (current ?: obj).click()
    }

    private fun clickBestEffort(target: UiObject2): Boolean {
        return try {
            val bounds = target.visibleBounds
            if (bounds.width() > 0 && bounds.height() > 0) {
                return device.click(bounds.centerX(), bounds.centerY())
            }

            if (target.isClickable) {
                target.click()
                return true
            }

            false
        } catch (_: StaleObjectException) {
            false
        }
    }

    private fun findTimerText(root: UiObject2): String? {
        val queue = ArrayDeque<UiObject2>()
        queue.add(root)

        while (queue.isNotEmpty()) {
            val current = queue.removeFirst()
            val text = runCatching { current.text }.getOrNull()
            if (!text.isNullOrBlank() && text.matches(Regex("\\d{2}:\\d{2}(?::\\d{2})?"))) {
                return text
            }
            runCatching { current.children }.getOrDefault(emptyList()).forEach(queue::addLast)
        }

        return null
    }

    private fun parseTimerTextToSeconds(timerText: String): Int {
        val parts = timerText.split(":").map { it.toIntOrNull() }
        require(parts.all { it != null }) { "Timer text '$timerText' is not numeric" }

        return when (parts.size) {
            2 -> (parts[0]!! * 60) + parts[1]!!
            3 -> (parts[0]!! * 3600) + (parts[1]!! * 60) + parts[2]!!
            else -> error("Unexpected timer format: '$timerText'")
        }
    }
}
