package com.gabstra.myworkoutassistant.composable

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun CustomBackHandler(
    enabled: Boolean = true,
    onSinglePress: () -> Unit,
    onDoublePress: () -> Unit,
    doublePressDuration: Long = 250L,
) {
    var lastBackPressTime by remember { mutableStateOf(0L) }
    val scope = rememberCoroutineScope()
    var backPressJob by remember { mutableStateOf<Job?>(null) }

    BackHandler(enabled = enabled) {
        val currentTime = System.currentTimeMillis()

        if (currentTime - lastBackPressTime < doublePressDuration) {
            backPressJob?.cancel()
            onDoublePress()
            lastBackPressTime = 0
        } else {
            lastBackPressTime = currentTime
            backPressJob = scope.launch {
                delay(doublePressDuration)
                onSinglePress()
                lastBackPressTime = 0
            }
        }
    }
}