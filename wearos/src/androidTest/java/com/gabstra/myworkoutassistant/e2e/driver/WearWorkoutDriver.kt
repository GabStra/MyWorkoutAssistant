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
import java.util.regex.Pattern

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

    /**
     * Scrolls within a specific container until the selector is found.
     * Use when the default scrollable (e.g. horizontal pager) would scroll the wrong element.
     */
    fun scrollUntilFoundWithin(
        containerSelector: BySelector,
        selector: BySelector,
        direction: Direction,
        initialWaitMs: Long = 1_000
    ): UiObject2? {
        device.wait(Until.findObject(selector), initialWaitMs)?.let { return it }

        val container = device.findObject(containerSelector) ?: return null
        val scrollable = container.findObject(By.scrollable(true)) ?: return null
        return runCatching {
            scrollable.scrollUntil(direction, Until.findObject(selector))
        }.getOrNull()
    }

    /**
     * Swipes the horizontal pager to change pages.
     * On Wear, Direction.LEFT advances to the next page (swipe left = content moves left = next).
     */
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

    /**
     * Navigates to the Exercises page (PageExercises) by swiping left until it is visible.
     * Works from RestScreen or ExerciseScreen where the pager includes an exercises tab.
     *
     * @param maxSwipes Maximum number of swipes to attempt
     * @return true if the exercises page became visible, false otherwise
     */
    fun navigateToExercisesPage(maxSwipes: Int = 4): Boolean {
        val exercisesPageSelector = By.desc("Exercise sets viewer")
        var swipeCount = 0
        while (swipeCount < maxSwipes) {
            if (device.wait(Until.hasObject(exercisesPageSelector), 1_000)) {
                return true
            }
            navigateToPagerPage(Direction.LEFT)
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
            swipeCount++
        }
        return device.wait(Until.hasObject(exercisesPageSelector), 2_000)
    }

    /**
     * Finds an element, scrolling in the given directions if not immediately visible.
     * Use when content may be off-screen (e.g. in a scrollable list).
     *
     * @param selector Selector for the element
     * @param initialWaitMs Time to wait before attempting scroll
     * @param directions Directions to try scrolling (e.g. UP then DOWN)
     * @return The found UiObject2, or null if not found
     */
    fun findWithScrollFallback(
        selector: BySelector,
        initialWaitMs: Long = 2_000,
        directions: List<Direction> = listOf(Direction.UP, Direction.DOWN)
    ): UiObject2? {
        device.wait(Until.findObject(selector), initialWaitMs)?.let { return it }
        for (direction in directions) {
            scrollUntilFound(selector, direction, 500)?.let { return it }
        }
        return null
    }

    fun dismissResumeDialogIfPresent(timeoutMs: Long = 2_000) {
        val resumeVisible = device.wait(Until.hasObject(By.textContains("Resume")), timeoutMs)
        if (resumeVisible) {
            device.pressBack()
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }
    }

    /**
     * Waits until the recovery (interrupted workout) dialog is visible.
     * Returns true if any of the recovery dialog indicators appear within [timeoutMs].
     */
    fun waitForRecoveryDialog(timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (isRecoveryDialogVisible()) return true
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    /**
     * Returns true if the recovery dialog is currently visible (no wait).
     */
    fun isRecoveryDialogVisible(): Boolean {
        return device.hasObject(By.desc("Recovery resume action")) ||
            device.hasObject(By.desc("Recovery discard action")) ||
            device.hasObject(By.text("Resume or discard this interrupted workout."))
    }

    /**
     * Clicks the Discard action in the recovery dialog.
     * Returns true when the dialog is no longer visible after retries.
     */
    fun clickRecoveryDiscard(timeoutMs: Long = 5_000): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (!isRecoveryDialogVisible()) return true

            val discard = scrollUntilFound(
                selector = By.desc("Recovery discard action"),
                direction = Direction.DOWN,
                initialWaitMs = 400
            )
                ?: scrollUntilFound(
                    selector = By.desc("Recovery discard action"),
                    direction = Direction.UP,
                    initialWaitMs = 200
                )
                ?: device.wait(Until.findObject(By.desc("Recovery discard action")), 500)
                ?: device.wait(Until.findObject(By.text("Discard")), 500)
                ?: device.findObject(By.textContains("Discard"))

            if (discard != null) {
                clickObjectOrAncestorInternal(discard)
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                if (device.wait(Until.gone(By.desc("Recovery discard action")), 1_500) ||
                    !isRecoveryDialogVisible()
                ) {
                    return true
                }

                // Compose/Wear semantics can resolve to non-clickable wrapper nodes.
                // Retry with coordinate click against a clickable ancestor.
                clickBestEffortOnObjectOrAncestor(discard)
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                if (device.wait(Until.gone(By.desc("Recovery discard action")), 1_500) ||
                    !isRecoveryDialogVisible()
                ) {
                    return true
                }

                runCatching { longPressByDesc("Recovery discard action", 1_200) }
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                if (device.wait(Until.gone(By.desc("Recovery discard action")), 1_500) ||
                    !isRecoveryDialogVisible()
                ) {
                    return true
                }
            }

            scrollRecoveryDialogDown()
        }

        return !isRecoveryDialogVisible()
    }

    /**
     * Clicks the Dismiss action in the recovery dialog. Fails if not found within [timeoutMs].
     */
    fun clickRecoveryDismiss(timeoutMs: Long = 5_000) {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (!isRecoveryDialogVisible()) return

            val dismiss = scrollUntilFound(
                selector = By.desc("Recovery dismiss action"),
                direction = Direction.DOWN,
                initialWaitMs = 400
            )
                ?: scrollUntilFound(
                    selector = By.desc("Recovery dismiss action"),
                    direction = Direction.UP,
                    initialWaitMs = 200
                )
                ?: device.wait(Until.findObject(By.desc("Recovery dismiss action")), 500)
                ?: device.wait(Until.findObject(By.text("Dismiss")), 500)
                ?: device.findObject(By.textContains("Dismiss"))

            if (dismiss != null) {
                clickObjectOrAncestorInternal(dismiss)
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                if (device.wait(Until.gone(By.desc("Recovery dismiss action")), 1_500) ||
                    !isRecoveryDialogVisible()
                ) {
                    return
                }

                clickBestEffortOnObjectOrAncestor(dismiss)
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                if (device.wait(Until.gone(By.desc("Recovery dismiss action")), 1_500) ||
                    !isRecoveryDialogVisible()
                ) {
                    return
                }
            }

            scrollRecoveryDialogDown()
        }

        error("Timed out waiting for recovery dismiss action (desc or text 'Dismiss') to appear")
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
        repeat(4) { attempt ->
            device.pressBack()
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)

            if (tryConfirmLongPressDialog(timeoutMs)) {
                return
            }

            // Tutorial overlays occasionally consume back/gesture input before dialog appears.
            dismissGotItIfPresent()
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)

            // Retry once more quickly in the same attempt after dismissing overlays.
            if (tryConfirmLongPressDialog(1_500)) {
                return
            }

            // Let the UI settle before next back attempt.
            if (attempt < 3) {
                device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
            }
        }

        val doneVisible = device.hasObject(By.desc("Done"))
        val skipRestVisible = device.hasObject(By.text("Skip Rest"))
        val setTypeVisible =
            device.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.BodyWeightSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.TimedDurationSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.EnduranceSetTypeDescription))
        val restTypeVisible = device.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription))
        val debugState = listOf(
            "doneVisible=$doneVisible",
            "skipRestVisible=$skipRestVisible",
            "setTypeVisible=$setTypeVisible",
            "restTypeVisible=$restTypeVisible"
        ).joinToString(", ")
        error("Timed out waiting for set confirmation dialog ('Done'). State: $debugState")
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

        // Validate the dialog actually closed; otherwise treat as failed confirmation.
        val dismissed = device.wait(Until.gone(By.desc("Done")), 1_500)
        if (!dismissed && device.hasObject(By.desc("Done"))) {
            return false
        }
        return true
    }

    /**
     * Reads the weight displayed on the current set screen (e.g. Weight Set screen).
     * Uses [SetValueSemantics.WeightValueDescription]; parses text or content description to Double.
     * Waits for the weight (or Weight Set screen) to appear and retries a few times to allow pager/UI to settle.
     * @return The weight in kg, or null if not found / parse failed.
     */
    fun readWeightOnSetScreen(timeoutMs: Long = 5_000): Double? {
        if (!waitForWeightSetScreen(timeoutMs)) {
            return readWeightFromScreenFallback(timeoutMs)
        }
        val deadline = System.currentTimeMillis() + 3_000
        repeat(5) {
            if (System.currentTimeMillis() >= deadline) return null
            val target = device.findObject(By.descContains(SetValueSemantics.WeightValueDescription))
                ?: device.findObject(By.descContains(SetValueSemantics.WeightSetTypeDescription))
            if (target != null) {
                val raw = readValueTextFromNode(target)
                raw?.replace(",", ".")?.toDoubleOrNull()?.let { return it }
            }
            device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        }
        return readWeightFromScreenFallback(1_000)
    }

    /**
     * Fallback: find visible text that looks like a weight value (integer in 50..150 kg).
     * Used when semantics are not exposed (e.g. on a pager page).
     */
    private fun readWeightFromScreenFallback(timeoutMs: Long): Double? {
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val nodes = device.findObjects(By.text(Pattern.compile("^[0-9]+$")))
            for (node in nodes) {
                val text = node.text?.trim() ?: continue
                val value = text.toDoubleOrNull() ?: continue
                if (value in 50.0..150.0) return value
            }
            device.waitForIdle(300)
        }
        return null
    }

    /**
     * Waits until the Weight Set screen or weight value is visible (e.g. after pager settles).
     */
    fun waitForWeightSetScreen(timeoutMs: Long): Boolean {
        return device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightValueDescription)),
            timeoutMs
        ) || device.wait(
            Until.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)),
            timeoutMs
        )
    }

    private fun readValueTextFromNode(target: UiObject2): String? {
        return try {
            val directText = target.text?.trim()
            if (!directText.isNullOrBlank()) return directText
            val queue = ArrayDeque<UiObject2>()
            queue.add(target)
            while (queue.isNotEmpty()) {
                val node = queue.removeFirst()
                val nodeText = node.text?.trim()
                if (!nodeText.isNullOrBlank()) return nodeText
                runCatching { node.children }.getOrDefault(emptyList()).forEach { queue.addLast(it) }
            }
            val desc = target.contentDescription?.toString()?.trim()
            if (!desc.isNullOrBlank()) {
                val parts = desc.split(":", limit = 2)
                if (parts.size == 2) {
                    val candidate = parts[1].trim()
                    if (candidate.isNotBlank()) return candidate
                }
            }
            null
        } catch (_: StaleObjectException) {
            null
        }
    }

    /**
     * On the auto-regulation (or calibration) RIR screen: select the given RIR value via the picker,
     * then confirm. Assumes RIR screen is already visible (e.g. "0 = Form Breaks" text present).
     * Default RIR is 2; use Add/Subtract to reach [targetRir], then Back to close picker, Back to open
     * confirm dialog, long-press Done to confirm.
     */
    fun selectRIRAndConfirm(targetRir: Int, timeoutMs: Long = 8_000) {
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        val rirNode = device.wait(Until.findObject(By.desc("RIR value")), timeoutMs)
            ?: error("RIR value control not found within ${timeoutMs}ms")
        rirNode.longClick()
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        val steps = targetRir - 2
        when {
            steps < 0 -> repeat(-steps) {
                clickLabel("Subtract", 2_000)
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            }
            steps > 0 -> repeat(steps) {
                clickLabel("Add", 2_000)
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            }
        }
        device.pressBack()
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
        device.pressBack()
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        val hasDone = device.wait(Until.hasObject(By.desc("Done")), timeoutMs)
        require(hasDone) { "Confirm RIR dialog (Done) did not appear" }
        longPressByDesc("Done", timeoutMs)
        device.waitForIdle(E2ETestTimings.MEDIUM_IDLE_MS)
    }

    fun skipRest(timeoutMs: Long = 3_000) {
        device.pressBack()
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        device.pressBack()
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)

        val dialogAppeared = device.wait(Until.hasObject(By.text("Skip rest?")), timeoutMs)
        require(dialogAppeared) { "Skip rest dialog did not appear" }
        longPressByDesc("Done", timeoutMs)
    }

    fun waitForWorkoutCompletion(timeoutMs: Long = 10_000) {
        val deadline = System.currentTimeMillis() + timeoutMs
        var completedVisible = false
        while (System.currentTimeMillis() < deadline && !completedVisible) {
            completedVisible =
                device.hasObject(By.text("Completed")) ||
                    device.hasObject(By.text("COMPLETED")) ||
                    device.hasObject(By.text("Workout completed")) ||
                    device.hasObject(By.text("Go Home")) ||
                    device.hasObject(By.desc("Go Home")) ||
                    // Some flows auto-return to selection quickly after completion.
                    device.hasObject(By.text("My Workout Assistant"))
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
        timeoutMs: Long = 10_000,
        useRestartTimer: Boolean = false,
        useRestartCalibration: Boolean = false
    ): RecoveryResumeResult {
        if (isLikelyInActiveWorkout(inWorkoutSelector)) {
            return RecoveryResumeResult(true, null, System.currentTimeMillis())
        }

        var resumeActionAtMs: Long? = null
        var enteredWorkoutAtMs: Long? = null
        val deadline = System.currentTimeMillis() + timeoutMs
        var workoutEntryOpened = false
        var timerChoiceSelected = false
        var calibrationChoiceSelected = false
        var optionalChoiceSearchPasses = 0
        val maxOptionalChoiceSearchPasses = 3

        while (System.currentTimeMillis() < deadline) {
            if (isLikelyInActiveWorkout(inWorkoutSelector)) {
                enteredWorkoutAtMs = System.currentTimeMillis()
                break
            }

            val timerChoiceClicked = if (useRestartTimer) {
                clickRestartTimerIfVisible()
            } else {
                clickContinueTimerIfVisible()
            }
            timerChoiceSelected = timerChoiceClicked || timerChoiceSelected

            val calibrationChoiceClicked = if (useRestartCalibration) {
                clickRestartCalibrationIfVisible()
            } else {
                clickContinueCalibrationIfVisible()
            }
            calibrationChoiceSelected = calibrationChoiceClicked || calibrationChoiceSelected

            if (timerChoiceClicked || calibrationChoiceClicked) {
                resumeActionAtMs = resumeActionAtMs ?: System.currentTimeMillis()
                if (waitForActiveWorkoutEntry(inWorkoutSelector, 4_000)) {
                    enteredWorkoutAtMs = System.currentTimeMillis()
                    break
                }
            }

            if (useRestartTimer && hasRestartTimerSelectedVisible()) {
                timerChoiceSelected = true
            }
            if (useRestartCalibration && hasRestartCalibrationSelectedVisible()) {
                calibrationChoiceSelected = true
            }

            val shouldSearchForOptionalChoices = isRecoveryDialogVisible() &&
                optionalChoiceSearchPasses < maxOptionalChoiceSearchPasses &&
                ((!useRestartTimer && !timerChoiceSelected) ||
                    (!useRestartCalibration && !calibrationChoiceSelected))

            // When restart options are requested, never fall through to generic Resume
            // until the explicit restart selection has been made.
            if ((useRestartTimer && !timerChoiceSelected) ||
                (useRestartCalibration && !calibrationChoiceSelected) ||
                shouldSearchForOptionalChoices
            ) {
                scrollRecoveryDialogDown()
                optionalChoiceSearchPasses += 1
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                continue
            }

            val resumeButton = findResumeButton()
            if (resumeButton != null) {
                clickObjectOrAncestorInternal(resumeButton)
                resumeActionAtMs = System.currentTimeMillis()
                device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
                if (waitForActiveWorkoutEntry(inWorkoutSelector, 2_500)) {
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

            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }

        val entered = enteredWorkoutAtMs != null
        return RecoveryResumeResult(
            enteredWorkout = entered,
            resumeActionAtMs = resumeActionAtMs,
            enteredWorkoutAtMs = enteredWorkoutAtMs
        )
    }

    private fun hasTimerChoiceVisible(): Boolean {
        return device.hasObject(By.desc("Recovery timer restart option")) ||
            device.hasObject(By.desc("Recovery timer continue option")) ||
            device.hasObject(By.textContains("Restart timer")) ||
            device.hasObject(By.textContains("Continue timer"))
    }

    private fun hasCalibrationChoiceVisible(): Boolean {
        return device.hasObject(By.desc("Recovery calibration restart option")) ||
            device.hasObject(By.desc("Recovery calibration continue option")) ||
            device.hasObject(By.textContains("Restart calibration")) ||
            device.hasObject(By.textContains("Continue calibration"))
    }

    private fun hasRestartTimerSelectedVisible(): Boolean {
        return device.hasObject(By.textContains("Restart timer (selected)")) ||
            device.hasObject(By.descContains("Restart timer (selected)"))
    }

    private fun hasRestartCalibrationSelectedVisible(): Boolean {
        return device.hasObject(By.textContains("Restart calibration (selected)")) ||
            device.hasObject(By.descContains("Restart calibration (selected)"))
    }

    private fun findResumeButton(): UiObject2? {
        val directMatch = findRecoveryActionButton(
            contentDescription = "Recovery resume action",
            text = "Resume"
        ) ?: findRecoveryActionButton(
            contentDescription = "Resume workout",
            text = "Resume"
        )
        if (directMatch != null) return directMatch

        return device.findObjects(By.clickable(true)).firstOrNull { obj ->
            val text = runCatching { obj.text }.getOrNull().orEmpty()
            val desc = runCatching { obj.contentDescription }.getOrNull().orEmpty()
            text.equals("Resume", ignoreCase = true) ||
                desc.equals("Recovery resume action", ignoreCase = true) ||
                desc.equals("Resume workout", ignoreCase = true)
        }
    }

    private fun clickContinueTimerIfVisible(): Boolean {
        val continueTimerButton = findRecoveryActionButton(
            contentDescription = "Recovery timer continue option",
            text = "Continue timer"
        )

        if (continueTimerButton != null) {
            clickObjectOrAncestorInternal(continueTimerButton)
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            return true
        }
        return false
    }

    private fun clickContinueCalibrationIfVisible(): Boolean {
        val continueCalibrationButton = findRecoveryActionButton(
            contentDescription = "Recovery calibration continue option",
            text = "Continue calibration"
        )

        if (continueCalibrationButton != null) {
            clickObjectOrAncestorInternal(continueCalibrationButton)
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            return true
        }
        return false
    }

    private fun clickRestartTimerIfVisible(): Boolean {
        val restartTimerButton = findRecoveryActionButton(
            contentDescription = "Recovery timer restart option",
            text = "Restart timer"
        )

        if (restartTimerButton != null) {
            clickObjectOrAncestorInternal(restartTimerButton)
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            return true
        }
        return false
    }

    private fun clickRestartCalibrationIfVisible(): Boolean {
        val restartCalibrationButton = findRecoveryActionButton(
            contentDescription = "Recovery calibration restart option",
            text = "Restart calibration"
        )

        if (restartCalibrationButton != null) {
            clickObjectOrAncestorInternal(restartCalibrationButton)
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
            return true
        }
        return false
    }

    private fun findRecoveryActionButton(
        contentDescription: String,
        text: String
    ): UiObject2? {
        val directMatch = device.findObject(By.desc(contentDescription))
            ?: device.findObject(By.text(text))
        if (directMatch != null && isClickableRecoveryAction(directMatch, contentDescription, text)) {
            return directMatch
        }

        return device.findObjects(By.clickable(true)).firstOrNull { obj ->
            isClickableRecoveryAction(obj, contentDescription, text)
        }
    }

    private fun isClickableRecoveryAction(
        obj: UiObject2,
        contentDescription: String,
        text: String
    ): Boolean {
        val objText = runCatching { obj.text }.getOrNull().orEmpty()
        val objDesc = runCatching { obj.contentDescription }.getOrNull().orEmpty()
        return objText.equals(text, ignoreCase = true) ||
            objDesc.equals(contentDescription, ignoreCase = true)
    }

    private fun scrollRecoveryDialogDown() {
        // Recovery dialogs on the Wear emulator frequently miss UiAutomator scroll-finished
        // events under load, which turns a simple search pass into a 1s timeout. A raw swipe is
        // cheaper and has been more reliable for revealing the optional restart/continue choices.
        verticalSwipe(Direction.DOWN)
        device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
    }

    private fun waitForActiveWorkoutEntry(inWorkoutSelector: BySelector, timeoutMs: Long): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            if (isLikelyInActiveWorkout(inWorkoutSelector)) {
                return true
            }
            device.waitForIdle(E2ETestTimings.SHORT_IDLE_MS)
        }
        return false
    }

    /**
     * Returns true if the device appears to be on an active workout screen (rest, set, etc.).
     * Must return false when the recovery dialog is still visible, since the dialog shows
     * text that matches inWorkoutSelector (e.g. time "HH:mm" contains ":") and would otherwise
     * cause the driver to skip clicking Continue timer / Resume.
     */
    private fun isLikelyInActiveWorkout(inWorkoutSelector: BySelector): Boolean {
        if (isRecoveryDialogVisible()) return false
        val anySetScreenVisible =
            device.hasObject(By.descContains(SetValueSemantics.WeightSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.BodyWeightSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.TimedDurationSetTypeDescription)) ||
                device.hasObject(By.descContains(SetValueSemantics.EnduranceSetTypeDescription))
        val anyCalibrationScreenVisible =
            device.hasObject(By.textContains("Set load")) ||
                device.hasObject(By.text("0 = Form Breaks"))
        val anyRestScreenVisible =
            device.hasObject(By.descContains(SetValueSemantics.RestSetTypeDescription))
        return device.hasObject(inWorkoutSelector) ||
            anySetScreenVisible ||
            anyCalibrationScreenVisible ||
            anyRestScreenVisible ||
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

    private fun clickBestEffortOnObjectOrAncestor(target: UiObject2): Boolean {
        var current: UiObject2? = target
        while (current != null && !current.isClickable) {
            current = current.parent
        }
        return clickBestEffort(current ?: target)
    }

    private fun dismissGotItIfPresent() {
        val gotIt = device.findObject(By.text("Got it")) ?: return
        clickBestEffort(gotIt)
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
