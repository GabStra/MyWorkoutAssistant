package com.gabstra.myworkoutassistant.composable

import android.widget.Toast
import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.gabstra.myworkoutassistant.data.VibrateGentle
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@Composable
fun CustomBackHandler(
    enabled: Boolean = true,
    onSinglePress: () -> Unit,
    onDoublePress: () -> Unit,
    doublePressDuration: Long = 400L,
) {
    var lastBackPressTime by remember { mutableLongStateOf(0L) }
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