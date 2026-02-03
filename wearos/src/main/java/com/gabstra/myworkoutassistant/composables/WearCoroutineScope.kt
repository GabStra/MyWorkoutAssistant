package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.runtime.remember
import kotlinx.coroutines.CoroutineExceptionHandler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
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
 * Use this instead of [androidx.compose.runtime.rememberCoroutineScope] in Wear composables
 * so UI-launched coroutines are covered by the app's single CEH.
 */
@Composable
fun rememberWearCoroutineScope(): CoroutineScope {
    val ceh = LocalWearCoroutineExceptionHandler.current
    val scope = remember {
        CoroutineScope(
            SupervisorJob() + Dispatchers.Main.immediate + (ceh ?: CoroutineExceptionHandler { _, _ -> })
        )
    }
    DisposableEffect(Unit) {
        onDispose { scope.cancel() }
    }
    return scope
}
