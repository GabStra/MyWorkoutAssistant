package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.staticCompositionLocalOf
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel

/**
 * CompositionLocal providing the app's single [CoroutineExceptionHandler] for Wear OS.
 * Set at the composition root (e.g. in [MyWorkoutAssistantTheme]) from MyApplication.
 * Default is null (e.g. tests); [rememberWearCoroutineScope] uses a no-op handler when null.
 */
val LocalWearCoroutineExceptionHandler = staticCompositionLocalOf<CoroutineExceptionHandler?> { null }

/**
 * Returns a [CoroutineScope] that is bound to composition (cancelled when the composable
 * leaves) and includes [LocalWearCoroutineExceptionHandler] when set, so unhandled exceptions
 * in launched coroutines are logged to file on Wear OS.
 *
 * The scope uses the composition's [CoroutineContext] (including [MonotonicFrameClock]) so
 * frame-based APIs like [androidx.compose.foundation.pager.PagerState.animateScrollToPage]
 * work correctly.
 *
 * Use this instead of [rememberCoroutineScope] in Wear composables so UI-launched coroutines
 * are covered by the app's single CEH.
 */
@Composable
fun rememberWearCoroutineScope(): CoroutineScope {
    val ceh = LocalWearCoroutineExceptionHandler.current
    val compositionScope = rememberCoroutineScope()
    val scope = remember(compositionScope, ceh) {
        val baseContext = compositionScope.coroutineContext.minusKey(Job)
        CoroutineScope(
            SupervisorJob() + baseContext + (ceh ?: CoroutineExceptionHandler { _, _ -> })
        )
    }
    DisposableEffect(Unit) {
        onDispose { scope.cancel() }
    }
    return scope
}
