package com.gabstra.myworkoutassistant.composable

import android.view.MotionEvent
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.height
import androidx.compose.ui.Alignment

import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material.Button
import androidx.wear.compose.material.ButtonDefaults
import androidx.wear.compose.material.Icon
import com.gabstra.myworkoutassistant.presentation.theme.MyColors
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job

import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(ExperimentalComposeUiApi::class)
fun Modifier.performActionOnLongPress(
    coroutineScope: CoroutineScope,
    thresholdMillis: Long = 5000L,
    intervalMillis: Long = 1000L,
    onAction: () -> Unit,
    onClick: () -> Unit
): Modifier = this.then(
    pointerInput(Unit) {
        detectTapGestures(
            onPress = { _ ->
                var actionHasBeenPerfomed= false
                val job = coroutineScope.launch {
                    delay(thresholdMillis)
                    do {
                        actionHasBeenPerfomed = true
                        onAction()
                        delay(intervalMillis)
                    } while (true)
                }
                tryAwaitRelease()
                job.cancel()
                if(!actionHasBeenPerfomed) onClick()
            }
        )
    }
)

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
        Box(
            modifier = Modifier
                .size(30.dp)
                .clip(CircleShape)
                .background(Color.Green)
                .performActionOnLongPress(coroutineScope,thresholdMillis= 1000,intervalMillis = 150, onAction = onPlusLongPress, onClick = onPlusClick),
            contentAlignment = Alignment.Center
        ) {
            Icon(imageVector = Icons.Filled.ArrowUpward, contentDescription = "Add")
        }
        Spacer(modifier = Modifier.height(5.dp))
        content()
        Spacer(modifier = Modifier.height(5.dp))
        Box(
            modifier = Modifier
                .size(30.dp)
                .clip(CircleShape)
                .background(Color.Red)
                .performActionOnLongPress(coroutineScope,thresholdMillis= 1000,intervalMillis = 150, onAction = onMinusLongPress, onClick = onMinusClick),
            contentAlignment = Alignment.Center
        ) {
            Icon(imageVector = Icons.Filled.ArrowDownward, contentDescription = "Subtract")
        }
    }
}