package com.gabstra.myworkoutassistant.composable

import android.view.MotionEvent
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.height
import androidx.compose.ui.Alignment

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDownward
import androidx.compose.material.icons.filled.ArrowUpward
import androidx.compose.material.icons.filled.ExposureNeg1
import androidx.compose.material.icons.filled.ExposurePlus1
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job

import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.performActionOnLongPress(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L, // Default threshold for long press
    intervalMillis: Long = 1000L, // Interval for repeated action post-long press
    onAction: () -> Unit, // Action to perform on long press and repeat
    onClick: () -> Unit // Action to perform on click
): Modifier {
    var job: Job? = null
    var touchDownTimestamp: Long = 0L

    return this.then(
        pointerInteropFilter { motionEvent ->
            when (motionEvent.action) {
                MotionEvent.ACTION_DOWN -> {
                    touchDownTimestamp = System.currentTimeMillis()
                    job = coroutineScope.launch {
                        delay(thresholdMillis)
                        while (true) {
                            onAction()
                            delay(intervalMillis)
                        }
                    }
                    true // Allow further event processing, e.g., onClick
                }
                MotionEvent.ACTION_UP -> {
                    job?.cancel()
                    if (System.currentTimeMillis() - touchDownTimestamp < thresholdMillis) {
                        // Touch was released before the threshold, indicating a click
                        onClick()
                    }
                    true // Allow further event processing, e.g., onClick
                }
                MotionEvent.ACTION_CANCEL -> {
                    job?.cancel()
                    true // Allow further event processing if needed
                }
                else -> false // Other events are not handled, allow them to propagate
            }
        }
    )
}

@Composable
fun ControlButtonsVertical(
    modifier: Modifier,
    onMinusClick: () -> Unit,
    onMinusLongPress: () -> Unit,
    onPlusClick: () -> Unit,
    onPlusLongPress: () -> Unit,
    content: @Composable () -> Unit
){
    val coroutineScope = rememberCoroutineScope()
    
    Column(modifier = modifier, horizontalAlignment = Alignment.CenterHorizontally,verticalArrangement = Arrangement.Center) {
        Button(
            onClick = {
            },
            modifier = Modifier.size(30.dp).performActionOnLongPress(coroutineScope,thresholdMillis= 1500,intervalMillis = 200, onAction = onPlusLongPress, onClick = onPlusClick),
            colors = ButtonDefaults.buttonColors(backgroundColor = Color.hsl(124f,0.27f,0.42f))
        ) {
            Icon(imageVector = Icons.Filled.ArrowUpward, contentDescription = "Add")
        }
        Spacer(modifier = Modifier.height(5.dp))
        content()
        Spacer(modifier = Modifier.height(5.dp))
        Button(
            onClick = {
            },
            modifier = Modifier.size(30.dp).performActionOnLongPress(coroutineScope,thresholdMillis= 1500,intervalMillis = 200, onAction = onMinusLongPress, onClick = onMinusClick),
            colors = ButtonDefaults.buttonColors(backgroundColor = Color.hsl(0f,0.44f,0.49f))
        ) {
            Icon(imageVector = Icons.Filled.ArrowDownward, contentDescription = "Subtract")
        }
    }
}