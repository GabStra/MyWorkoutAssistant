package com.gabstra.myworkoutassistant.composables

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput

internal data class TopOverlayEntry(
    val owner: String,
    val token: Long,
    val content: @Composable BoxScope.() -> Unit
)

@Stable
class TopOverlayController internal constructor() {
    companion object {
        const val OWNER_SET_SCREEN_TUTORIAL = "workout_set_tutorial"
    }

    private var nextToken by mutableLongStateOf(0L)
    private var entry by mutableStateOf<TopOverlayEntry?>(null)

    val isVisible: Boolean
        get() = entry != null

    /**
     * Current overlay owner, or null if no overlay. Composable reads subscribe to overlay changes.
     */
    val currentOwner: String?
        get() = entry?.owner

    fun show(owner: String, content: @Composable BoxScope.() -> Unit) {
        nextToken += 1L
        entry = TopOverlayEntry(
            owner = owner,
            token = nextToken,
            content = content
        )
    }

    fun clear(owner: String) {
        val current = entry ?: return
        if (current.owner == owner) {
            entry = null
        }
    }

    internal fun currentEntry(): TopOverlayEntry? = entry
}

val LocalTopOverlayController = staticCompositionLocalOf<TopOverlayController> {
    error("TopOverlayController not provided")
}

@Composable
fun rememberTopOverlayController(): TopOverlayController {
    return remember { TopOverlayController() }
}

@Composable
fun TopOverlayHost(
    controller: TopOverlayController,
    modifier: Modifier = Modifier
) {
    val currentEntry = controller.currentEntry() ?: return

    BackHandler(enabled = true) {}

    Box(modifier = modifier.fillMaxSize()) {
        Box(
            modifier = Modifier
                .fillMaxSize()
                .consumeAllPointerInput()
        )
        Box(modifier = Modifier.fillMaxSize()) {
            currentEntry.content.invoke(this)
        }
    }
}

private fun Modifier.consumeAllPointerInput(): Modifier {
    return pointerInput(Unit) {
        awaitPointerEventScope {
            while (true) {
                val event = awaitPointerEvent()
                event.changes.forEach { pointerInputChange ->
                    pointerInputChange.consume()
                }
            }
        }
    }
}
