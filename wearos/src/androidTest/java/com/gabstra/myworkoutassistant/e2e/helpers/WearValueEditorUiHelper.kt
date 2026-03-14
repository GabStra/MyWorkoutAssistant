package com.gabstra.myworkoutassistant.e2e.helpers

import androidx.test.uiautomator.By
import androidx.test.uiautomator.StaleObjectException
import androidx.test.uiautomator.UiDevice
import androidx.test.uiautomator.UiObject2
import androidx.test.uiautomator.Until

object WearValueEditorUiHelper {
    fun incrementIntegerValueByOne(
        device: UiDevice,
        valueDescription: String,
        timeoutMs: Long = 5_000
    ): Int? {
        val target = device.wait(
            Until.findObject(By.descContains(valueDescription)),
            2_000
        )
        if (target == null) {
            println("WARN: incrementIntegerValueByOne missing target for $valueDescription")
            return null
        }

        val beforeValue = readValueText(target)
        val beforeInt = beforeValue?.let(::parseIntValue)
        if (beforeInt == null) {
            println("WARN: incrementIntegerValueByOne missing readable value for $valueDescription")
            return null
        }

        val addButton = enterEditMode(
            device = device,
            target = target,
            valueDescription = valueDescription,
            fallbackValueText = beforeValue
        )
        if (addButton == null) {
            return null
        }

        if (!clickBestEffort(device, addButton)) {
            println("WARN: incrementIntegerValueByOne Add not clickable for $valueDescription")
            return null
        }

        device.waitForIdle(300)

        val updatedValue = waitForValueText(
            device = device,
            valueDescription = valueDescription,
            previousValue = beforeValue,
            expectedValue = (beforeInt + 1).toString(),
            timeoutMs = timeoutMs
        )

        closeEditor(device, valueDescription)

        val updatedInt = updatedValue?.let(::parseIntValue)
        if (updatedInt == null || updatedInt == beforeInt) {
            println(
                "WARN: incrementIntegerValueByOne value did not update for $valueDescription " +
                    "(before=$beforeInt after=${updatedInt ?: "null"})"
            )
            return null
        }

        return updatedInt
    }

    private fun closeEditor(device: UiDevice, valueDescription: String) {
        if (!isEditorVisible(device)) {
            return
        }

        val closeButton = waitForButtonByLabel(device, "Close", 1_000)
        if (closeButton != null) {
            if (!clickBestEffort(device, closeButton)) {
                println("WARN: incrementIntegerValueByOne Close not clickable for $valueDescription")
                device.pressBack()
            }
        } else {
            device.pressBack()
        }
        device.waitForIdle(500)
    }

    private fun enterEditMode(
        device: UiDevice,
        target: UiObject2,
        valueDescription: String,
        fallbackValueText: String?
    ): UiObject2? {
        val candidates = mutableListOf<UiObject2>()
        candidates += target

        var ancestor = runCatching { target.parent }.getOrNull()
        repeat(3) {
            if (ancestor != null) {
                val currentAncestor = ancestor ?: return@repeat
                candidates += currentAncestor
                ancestor = runCatching { currentAncestor.parent }.getOrNull()
            }
        }

        candidates += runCatching { target.children }.getOrDefault(emptyList())
        if (!fallbackValueText.isNullOrBlank()) {
            device.findObject(By.text(fallbackValueText))?.let { candidates += it }
        }

        for ((index, candidate) in candidates.withIndex()) {
            tryEnterEditModeWithCandidate(
                device = device,
                candidate = candidate,
                context = "incrementIntegerValueByOne candidate[$index] for $valueDescription"
            )?.let { return it }
        }

        println("WARN: incrementIntegerValueByOne failed to enter edit mode for $valueDescription")
        return null
    }

    private fun tryEnterEditModeWithCandidate(
        device: UiDevice,
        candidate: UiObject2,
        context: String
    ): UiObject2? {
        if (performNativeLongClick(candidate)) {
            device.waitForIdle(300)
            waitForEditControls(device = device, context = "$context native", timeoutMs = 3_000)
                ?.let { return it }
        }

        if (performGestureLongPress(device, candidate)) {
            device.waitForIdle(300)
            waitForEditControls(device = device, context = "$context gesture", timeoutMs = 3_000)
                ?.let { return it }
        }

        return null
    }

    private fun waitForButtonByLabel(
        device: UiDevice,
        label: String,
        timeoutMs: Long = 2_000
    ): UiObject2? {
        return device.wait(Until.findObject(By.desc(label)), timeoutMs)
            ?: device.wait(Until.findObject(By.text(label)), timeoutMs)
    }

    private fun isEditorVisible(device: UiDevice): Boolean {
        return device.findObject(By.desc("Add")) != null ||
            device.findObject(By.text("Add")) != null ||
            device.findObject(By.desc("Subtract")) != null ||
            device.findObject(By.text("Subtract")) != null
    }

    private fun waitForEditControls(
        device: UiDevice,
        context: String,
        timeoutMs: Long = 2_000
    ): UiObject2? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            val addButton = device.findObject(By.desc("Add")) ?: device.findObject(By.text("Add"))
            val subtractButton = device.findObject(By.desc("Subtract")) ?: device.findObject(By.text("Subtract"))
            if (addButton != null && subtractButton != null) {
                return addButton
            }
            device.waitForIdle(200)
        }

        println("WARN: $context missing Add/Subtract buttons")
        return null
    }

    private fun clickBestEffort(device: UiDevice, target: UiObject2): Boolean {
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
        } catch (e: StaleObjectException) {
            false
        }
    }

    private fun performNativeLongClick(target: UiObject2): Boolean {
        if (!runCatching { target.isLongClickable }.getOrDefault(false)) {
            return false
        }

        val longClickSuccess = runCatching {
            target.longClick()
            true
        }.getOrDefault(false)
        return longClickSuccess
    }

    private fun performGestureLongPress(device: UiDevice, target: UiObject2): Boolean {
        val bounds = runCatching { target.visibleBounds }.getOrNull() ?: return false
        if (bounds.width() <= 0 || bounds.height() <= 0) {
            return false
        }

        val centerX = bounds.centerX()
        val centerY = bounds.centerY()

        return runCatching {
            device.swipe(centerX, centerY, centerX, centerY, 200)
            true
        }.getOrDefault(false)
    }

    private fun waitForValueText(
        device: UiDevice,
        valueDescription: String,
        previousValue: String?,
        expectedValue: String?,
        timeoutMs: Long
    ): String? {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            device.waitForIdle(200)
            val currentValue = readValueText(device, valueDescription)
            if (!currentValue.isNullOrBlank()) {
                if (expectedValue != null) {
                    if (currentValue == expectedValue) return currentValue
                } else if (previousValue == null || currentValue != previousValue) {
                    return currentValue
                }
            }
            device.waitForIdle(200)
        }
        return null
    }

    private fun readValueText(device: UiDevice, valueDescription: String): String? {
        val target = device.findObject(By.descContains(valueDescription)) ?: return null
        return readValueText(target)
    }

    private fun readValueText(target: UiObject2): String? {
        return try {
            val directText = target.text?.trim()
            if (!directText.isNullOrBlank()) {
                return directText
            }

            val queue: ArrayDeque<UiObject2> = ArrayDeque()
            queue.add(target)
            while (queue.isNotEmpty()) {
                val node = queue.removeFirst()
                val nodeText = node.text?.trim()
                if (!nodeText.isNullOrBlank()) {
                    return nodeText
                }
                node.children.forEach(queue::add)
            }

            val description = target.contentDescription?.trim()
            if (!description.isNullOrBlank()) {
                val parts = description.split(":", limit = 2)
                if (parts.size == 2) {
                    val candidate = parts[1].trim()
                    if (candidate.isNotBlank()) {
                        return candidate
                    }
                }
            }

            null
        } catch (e: StaleObjectException) {
            null
        }
    }

    private fun parseIntValue(text: String): Int? {
        return Regex("""-?\d+""").find(text)?.value?.toIntOrNull()
    }
}
